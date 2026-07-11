---
type: Goal Teams Testing Rules
title: Goal Teams Testing Rules
description: 后端架构先行、TDD、API 集成测试、前端 E2E 和独立测试派发规则。
tags: [goal-teams, testing, tdd, e2e, okf]
timestamp: 2026-07-09T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Testing Rules

只在任务涉及实现、测试、API、CLI、MCP、前端交互、E2E、QA、验收或测试报告时读取本文件。

## 必读文件

- `prompts/packets/handoff-artifacts.md`
- `references/subagent-dispatch-protocol.md`
- `prompts/packets/harness-contract.md`
- 对应成员包：`prompts/members/<role>/prompt.md`，必要时读取同目录 `template.md`、`workflow.md`、`scripts.md`

## 最小颗粒度

每个功能切片必须在版本子目录 `TaskList.md` 中拆到以下颗粒度；不适用项写 `not_applicable_reason`：

| 顺序 | 任务 | 默认 Owner |
| --- | --- | --- |
| 1 | 需求规格卡 | `goal_requirements_analyst` |
| 2 | PRD | `goal_product` |
| 3 | 页面规格卡 | `goal_product` 或 `goal_frontend` |
| 4 | HTML 原型 | `goal_frontend` |
| 5 | 前端架构设计 | `goal_frontend` |
| 6 | 后端架构设计 | `goal_backend` |
| 7 | 前端开发 | `goal_frontend` |
| 8 | 后端 TDD 单元测试用例 | `goal_unit_test_designer` |
| 9 | 后端开发 | `goal_backend` |
| 10 | 后端单元测试执行 | `goal_unit_test_runner` |
| 11 | API 集成测试脚本生成 | `goal_api_integration_test_designer` |
| 12 | API 集成测试计划 | `goal_api_integration_test_designer` |
| 13 | API 集成测试执行 | `goal_api_integration_test_runner` |
| 14 | E2E 测试用例 | `goal_e2e_test_designer` |
| 15 | E2E 测试执行 | `goal_e2e_test_runner` |
| 16 | BugFix | 对应实现 Owner |
| 17 | 测试报告 | `goal_qa` 或 `goal_docs` |

## 后端与 API

- 后端、API、TDD 或完整测试编排使用 schema 机器值 `profile=full`；纯 CLI 且不含 UI 时仍为 `full`，但不得加载 UI 条件规则。
- 后端开发前必须先生成或更新 Backend Architecture Design。
- 后端遵循 TDD：`goal_unit_test_designer` 先写单元测试用例，`goal_backend` 再实现，`goal_unit_test_runner` 独立执行并记录红/绿证据。
- 单元测试作者、后端实现者和单元测试执行者不能是同一唯一 subagent。
- 架构设计完成后，可以并行派发 `goal_api_integration_test_designer` 生成 API 集成测试脚本；默认脚本语言为 Python，默认测试框架为 `pytest`，除非项目已有更明确技术栈。
- 单元测试通过后，由 `goal_api_integration_test_runner` 执行 API 集成测试；无法执行时写阻塞、原因和风险。

## 前端与 E2E

- 前端开发前必须先生成或更新 Frontend Architecture Design；不适用时写 `not_applicable_reason`。
- 前端开发完成后，由 `goal_e2e_test_designer` 生成 E2E 测试用例，再由 `goal_e2e_test_runner` 执行。
- E2E 用例作者不能作为唯一执行者。
- UI 任务的 E2E 和像素对比细节读取 `references/rules-ui.md`。

## 验证和打回

- 每个实现、文档或测试任务都必须有 Harness 契约、证据或 `not_applicable_reason`。
- 从 Harness 内层 `task_type`、`required_review_class` 与风险推导最低 `review_class`；comparison/safety 使用 LLM + 脚本双重复核，structural/semantic 不互代，只执行适用复核并记录经独立 reviewer 接受的结构化 N/A；记录到 `prompts/packets/dual-review-record.md`。
- 实现者自测不能替代独立校验。
- Evidence 不足时使用 `task_state=running|blocked` 与 `check_state=failed|blocked`；不得改写成 accepted/achieved。
