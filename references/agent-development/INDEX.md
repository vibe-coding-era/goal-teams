---
type: Agent Development Reference Index
title: Agent 产品开发资料索引
description: 为 Agent 产品经理、产品、前端、后端和测试成员按需加载的开发资料入口。
tags: [goal-teams, agent-development, v2.48]
timestamp: 2026-07-29T00:00:00+08:00
okf_version: "0.1"
---

# Agent 产品开发资料索引

本目录是开发方法与来源映射，不是任何厂商运行时 adapter，也不授权外部操作。成员只能按 Goal Packet 的 `context_refs` 加载需要的分片。

| 场景 | 读取资料 | 主要成员 |
| --- | --- | --- |
| 产品定义、用户旅程、范围/权限 | [产品设计模式](product-design-patterns.md)、[平台映射](platform-reference-matrix.md) | `goal_agent_product_manager`、`goal_product` |
| Prompt、上下文、记忆、缓存 | [Prompt/上下文/缓存](prompt-context-cache.md) | 产品、前后端、测试 |
| MCP、外部工具、浏览器、Computer Use、Playwright | [工具与交互](tool-browser-computer-use.md) | 前后端、QA、E2E |
| 拆分/组合系统模块 | [架构模式](architecture-patterns.md) | 产品、前后端 |
| 测试、评估、治理与安全 | [测试与安全](testing-evaluation-safety.md) | QA、测试设计/执行、Reviewer |

产品品牌只在[平台映射](platform-reference-matrix.md)中以 `documented`、`contract_mapped_not_runtime_verified`、`unknown` 或 `not_found` 表示证据状态。不得从产品名称推断内部 Prompt 装配、缓存键、跨会话记忆或可用工具。
