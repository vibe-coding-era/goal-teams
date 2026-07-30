---
type: Agent Product Pattern Catalog
title: 可组合 Agent 产品设计方案
description: 三套可拆分、可组合的 Agent 产品设计方案及其模块合同。
tags: [goal-teams, agent-development, product-design, patterns]
timestamp: 2026-07-29T00:00:00+08:00
okf_version: "0.1"
---

# 可组合 Agent 产品设计方案

## 共同模块接口

所有方案按以下接口组合，任何模块均可被独立替换：

`Capability Contract → Context/Memory → Prompt Assembly/Cache → Tool Gateway → Execution/Approval → Observation/Evidence`

模块输入输出必须版本化；`Tool Gateway` 不得绕开 `Execution/Approval`，`Observation/Evidence` 不得从模型自述生成通过结论。

## 方案 A：受控任务执行 Agent

适用：文件、文档、代码或数据任务的单目标委派。

| 可独立启用模块 | 责任 | 依赖 |
| --- | --- | --- |
| 任务收件箱与 Plan | 目标、子任务、状态、停止条件 | Capability Contract |
| 工具网关 | 工具 allowlist、权限与审计 | Execution/Approval |
| 结果审阅 | diff、结构化输出、重试/回滚 | Observation/Evidence |

非目标：不宣称多 Agent 并行、跨会话记忆或桌面控制。

## 方案 B：上下文协作与工作流 Agent

适用：多角色协作、长任务、并行隔离与交接。

| 可独立启用模块 | 责任 | 依赖 |
| --- | --- | --- |
| Context Broker | 选择最小资料切片、版本与来源 | Context/Memory |
| Handoff Ledger | owner/validator、状态、Evidence、冲突 | Observation/Evidence |
| Workflow Router | 按风险分派角色、重试与人工升级 | Capability Contract |

非目标：不以“多个 Agent”替代审批、独立验证或业务完成断言。

## 方案 C：浏览器/桌面操作 Agent

适用：必须进入真实网页或桌面 UI 的受控流程。

| 可独立启用模块 | 责任 | 依赖 |
| --- | --- | --- |
| 浏览器检查 | Playwright/DOM、状态矩阵、trace | Tool Gateway |
| 视觉执行 | Browser/Computer Use 目标窗口、交接与截图 | Execution/Approval |
| 人工接管 | 敏感操作、拒绝、异常和回读 | Capability Contract |

非目标：不自动处理凭证、支付、删除、权限变更或安全确认。

## 组合例

- A + B：具备可审计交接的工具执行工作流。
- A + C：由结构化工具优先、视觉执行兜底的单任务 Agent。
- A + B + C：需要独立上下文、工具治理与 UI 证据的全链路方案；必须增加独立 QA 和明确成本/轮次 Budget Gate。
