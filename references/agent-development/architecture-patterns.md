---
type: Agent Architecture Pattern Catalog
title: 可组合 Agent 架构设计方案
description: 与产品方案一一对应的解耦架构、数据边界和失败处理规则。
tags: [goal-teams, agent-development, architecture, patterns]
timestamp: 2026-07-29T00:00:00+08:00
okf_version: "0.1"
---

# 可组合 Agent 架构设计方案

## 基础分层

| 层 | 可替换实现 | 不变量 |
| --- | --- | --- |
| Product/API | Chat、任务队列、工作流画布 | 明确用户意图、授权与可见状态。 |
| Orchestrator | 单 Agent loop、状态机、队列 | 只调度声明能力；超限停止。 |
| Context Plane | 文件检索、知识库、短期状态、memory | 来源、版本、敏感级别与 TTL 可追溯。 |
| Tool Plane | MCP、API、CLI、Playwright、Browser、Computer Use | 最小权限、参数验证、审计、超时和幂等。 |
| Evidence Plane | trace、日志、screenshots、assertion results | 绑定输入、执行、目标版本和独立验证。 |

## 架构 1：单 Agent + 受控工具

前端显示 Plan/状态/批准；后端执行可恢复任务状态机；工具适配器只接收已验证参数。适合方案 A。缓存可只覆盖稳定 Prompt/工具 schema，不能缓存用户私密动态尾部。

## 架构 2：事件账本 + 隔离工作单元

每个成员或任务单元持有独立 context snapshot、工作目录和 run identity；中心 ledger 只合并 revision-bound event。适合方案 B，支持并行但同一写入范围仍单 owner。失败以 `failed`、`blocked`、`retest_required` 等正交状态表示。

## 架构 3：分级执行器

结构化 API/MCP、Playwright/Browser、Computer Use 三个 adapter 均实现同一 Action Contract：`request → approval → execution → observed_result → evidence`。适合方案 C 或三方案组合；高风险动作只能升级到人工，不能向低层降级绕过。

## 架构评审清单

- 数据是否跨 session、跨用户或跨工具边界流动？是否有隔离与 redaction？
- Prompt/context 是否引用可版本化来源，而非拼接不可追溯聊天历史？
- 缓存是否区分静态规则和动态/敏感内容，并暴露真实可用的观测数据？
- 工具适配器是否可拒绝、超时、取消、重试/补偿并记录真实结果？
- Browser/Computer Use 是否提供同一流程的批准、回读和人工接管？
- Evidence 是否足以区分“模型说完成”与“系统实际完成”？
