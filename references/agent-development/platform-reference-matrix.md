---
type: Platform Evidence Matrix
title: Agent 产品开发平台来源矩阵
description: Codex、Claude Cowork、Qoder/QoderWork、WorkBuddy 与 Trae 的公开来源及可声明边界。
tags: [goal-teams, agent-development, evidence, platforms]
timestamp: 2026-07-29T00:00:00+08:00
okf_version: "0.1"
---

# Agent 产品开发平台来源矩阵

检索日期：`2026-07-29`。本表服务于产品设计与合同选型，不能证明 Goal Teams 已在这些产品中完成 adapter 或实机验证。

| 产品 surface | 官方来源确认的设计输入 | 资料状态 | 禁止推断 |
| --- | --- | --- | --- |
| Codex | Skills 将 instructions/resources/scripts 打包；Browser 与 Computer Use 均有独立批准、权限与 surface 边界；MCP 工具可配置审批策略。 | `documented` | 不从文档推断 provider Prompt Cache key、TTL、命中率或每个账号/地区可用性。 |
| Claude Cowork（用户称 CoWork） | Cowork 面向委派式多步骤工作；Project 可组织文件、指令、链接和专用 memory；官方 Computer Use 给出 Connector → Chrome browser → screen interaction 的优先顺序。 | `documented` | 项目 memory 不等于跨产品同步；公开的短期数据缓存不等于 Prompt Cache；不把本地/远程执行默认值视为所有部署相同。 |
| Qoder / QoderWork | Qoder Agent Mode 具备计划、项目上下文、文件/终端/MCP；QoderWork 的 Awareness 资料说明文件、项目、用户和本地索引分层；Qoder CLI 公开给出 `@playwright/mcp` 安装示例。 | `documented` | 不把“自动执行”理解为无审批；不能假定 QoderWork 与 Qoder CLI 权限模型相同，也不把浏览器 connector 说成全桌面 Computer Use。 |
| Tencent WorkBuddy | WorkBuddy 官方资料确认可规划本地文件任务、Skills/Agent Browser、可编辑/遗忘的个人 memory、MCP 接入和网络/MCP 安全控制。 | `documented` | 未公开 Prompt 编程指南、模型 Prompt Cache 或 Playwright 底层实现；Agent Browser 不能被写成 Playwright 或全桌面 Computer Use。 |
| Trae / TRAE Work | TRAE 官方产品页/更新日志记录自定义 agent、tools/skills/MCP、Rules/Memory、浏览器 Preview/DevTools，以及 TRAE Work 的 worktree/远程桌面控制。 | `documented_limited` | Preview/DevTools 不等于 Playwright CLI；远程桌面控制不等于已证实 Agent 可操作任意本地应用；当前 Goal Teams Trae adapter 仍是 `capability_probe_required`。 |

## 来源

- Codex：[Browser](https://learn.chatgpt.com/docs/browser)、[Computer Use](https://learn.chatgpt.com/docs/computer-use)、[Build skills](https://learn.chatgpt.com/docs/build-skills)、[MCP](https://learn.chatgpt.com/docs/mcp)
- Claude Cowork：[Projects](https://claude.com/docs/cowork/guide/projects)、[Computer Use](https://support.claude.com/en/articles/14128542-let-claude-use-your-computer-in-cowork)、[Architecture overview](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview)
- Qoder / QoderWork：[Prompt guide](https://docs.qoder.com/qoderwork/prompt-guide)、[Awareness](https://docs.qoder.com/qoderwork/memory)、[Browser Agent](https://docs.qoder.com/user-guide/chat/browser-agent)、[CLI MCP](https://docs.qoder.com/en/cli/mcp-servers)
- Tencent WorkBuddy：[Quickstart](https://www.workbuddy.ai/docs/workbuddy/Quickstart)、[Skills Market](https://www.workbuddy.ai/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)、[Memory](https://www.workbuddy.ai/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Memory)、[MCP](https://www.workbuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/MCP-Guide)、[Security](https://www.workbuddy.ai/docs/cli/security)
- Trae：[IDE](https://www.trae.ai/ide/)、[Changelog](https://www.trae.ai/ja/changelog)；当前 Goal Teams 合同见 [Trae adapter](../runtime-adapters/trae.md)

## 使用规则

1. PRD 必须把产品假设、来源和可验证验收分开。
2. 若本表未确认某能力，产品成员只能提出 discovery 或人工验证任务；不得写入已支持的功能清单。
3. 真实环境验证完成前，任何平台比较结论均为 `documented`，不是 `executed`；查无公开证据写 `not_found`，资料不足写 `unknown`，不得从产品名称推断能力。
