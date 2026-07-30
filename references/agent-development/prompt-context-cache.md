---
type: Agent Design Protocol
title: Prompt、上下文、记忆与缓存合同
description: 将 Agent 输入装配、上下文边界、记忆和缓存观测解耦的产品与工程规则。
tags: [goal-teams, agent-development, prompting, context, cache]
timestamp: 2026-07-29T00:00:00+08:00
okf_version: "0.1"
---

# Prompt、上下文、记忆与缓存合同

本版本只在 `references/prompt-cache-manifest.json` 中按实测 stable route bytes 重校相应静态预算；该预算不是 provider Prompt Cache 的 key、TTL、命中率或费用证明。

## Prompt 编程

每次执行都构造成可审阅合同，而不是不可解释的长 Prompt：

1. `goal`：用户可观察的结果与完成标准。
2. `context_refs`：版本化资料、当前任务状态与允许的检索结果；声明来源、时效与信任级别。
3. `constraints`：范围、禁止动作、审批点、输出格式与停止条件。
4. `tool_policy`：可调用工具、参数/路径/域名边界与确认要求。
5. `verification`：输入、处理、期望输出、逐项断言和 Evidence 位置。

提示词必须把网页、工具输出、截图和外部文档视作不可信数据，不能把其中的指令提升为系统/用户授权。

## 上下文与记忆

| 层 | 内容 | 生命周期 | 规则 |
| --- | --- | --- | --- |
| 当前任务上下文 | 需求、任务状态、最小必要文件切片 | 当前 run | 只加载 `context_refs`；超出范围写 `scope_change_proposal`。 |
| 项目知识 | 已批准规范、架构、长期约定 | 项目版本 | 可检索、版本绑定、可追溯；不能用聊天记忆替代 SSOT。 |
| 可写记忆 | 用户明确要求保存的偏好或已核验摘要 | 明确持久化后 | 有 owner、修订、脱敏与删除/修正路径。 |
| 外部资料 | MCP/浏览器/搜索返回 | 单次取用 | 记录来源和时间；敏感数据不进入公共日志。 |

产品不得承诺“无限上下文”或“自动跨会话记忆”。具体产品的 memory 行为只以[平台映射](platform-reference-matrix.md)的来源为准。

## 缓存

- 缓存目标是降低重复成本或延迟，不能改变授权、数据隔离、工具策略、任务语义或 Evidence。
- 将稳定前缀（角色合同、长期规则、工具 schema）与动态尾部（任务、最新文件摘要、结果）分离；动态数据不应污染稳定 cache identity。
- 仅在宿主提供可核验 usage receipt 时记录命中率。未提供则写 `unavailable`，不能按 token 估算。
- 缓存失效条件包括：权限、工具 schema、稳定规则、模型/运行时身份、资料修订或安全策略变更。失效后保留历史 Evidence，按影响分析标记 `stale` / `retest_required`，不把历史事实直接写成 `invalid`。

## 交付物

产品成员提供 Prompt Contract、上下文数据分级和缓存观测需求；后端实现装配与审计字段；前端展示来源/状态/批准；测试成员以可控输入验证装配、权限与失效语义。
