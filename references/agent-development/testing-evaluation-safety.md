---
type: Agent Testing and Safety Protocol
title: Agent 开发测试、评估与安全规则
description: Agent 行为、工具调用、上下文、缓存与 UI 证据的独立测试合同。
tags: [goal-teams, agent-development, testing, evaluation, safety]
timestamp: 2026-07-29T00:00:00+08:00
okf_version: "0.1"
---

# Agent 开发测试、评估与安全规则

## 最小测试分母

| 类别 | 必测行为 |
| --- | --- |
| Prompt/Context | 指令优先级、资料来源、上下文裁剪、外部内容注入拒绝、版本漂移。 |
| Memory/Cache | 写入授权、隔离、过期/失效、不可用观测、历史 Evidence 影响分析。 |
| Tools/MCP | allow/ask/deny、参数边界、超时、重试、失败回读、审计事件。 |
| Browser/Playwright | 输入、处理、期望输出、DOM/业务断言、截图/trace、清理。 |
| Computer Use | 应用/窗口范围、系统权限、人工接管、拒绝终态、敏感操作阻断。 |
| 产品体验 | Plan、运行、等待批准、失败、恢复和完成状态对用户可解释。 |

## 评估与 Evidence

- 先写 Expected Output 与逐项 Assertions，再执行；HTTP 200、截图、日志或 exit code 只能是辅助证据。
- 对外部写入与浏览器/桌面动作使用受控环境或 mock；真实环境测试须取得授权并记录环境指纹。
- 测试设计者、执行者、实现者与最终 reviewer 按任务等级分离；实现者不能是唯一验证者。
- 红队项至少覆盖 prompt injection、越权工具、秘密泄露、错误恢复、虚假完成和过期上下文。

## 安全停止条件

缺少来源、权限、测试环境、独立检查或关键断言时，写 `blocked` / `not_run`；不得使用模型自述、模拟成功或通用产品声明替代 Evidence。任何外部写入、凭证、支付、权限/安全变更均需用户或受信系统的明确授权。
