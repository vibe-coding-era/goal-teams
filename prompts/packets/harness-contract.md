---
type: Harness Contract Template
title: Harness Contract OKF 模板
description: SPEC -> Harness -> Evidence -> Audit 验证链的 OKF 模板。
tags: [goal-teams, okf, harness]
timestamp: 2026-07-01T00:00:00+08:00
okf_version: "0.1"
---

# Harness Contract

Goal Teams 使用 `SPEC -> Harness -> Evidence -> Audit` 的验证链。

```text
Harness Contract（验证契约）:
- checks:
- commands:
- artifact_checks:
- tdd_checks:
- api_integration_checks:
- e2e_checks:
- evidence_paths:
- failure_report:
- not_applicable_reason:
```

可选扩展字段：

```text
- pixel_diff_checks:
- approval_gate:
- pipeline_state:
- benchmark_refs:
```

规则：

- Harness 不是新增 runtime 执行能力；它必须表现为 Plan、tasklist、Member Goal Packet、test plan 和 acceptance 中的字段、命令、人工检查、证据路径和失败报告格式。
- 每个实现、文档或测试任务都要写清 Harness 契约；若不适用，必须写 `not_applicable_reason`。
- 后端 Harness 必须能区分 TDD 单元测试用例、单元测试执行、API 集成测试脚本、API 集成测试执行；API 集成测试默认 Python + pytest，替代方案必须说明项目依据。
- 前端 Harness 必须能区分前端实现、E2E 用例生成和 E2E 执行；用例作者和执行者不能是同一唯一 subagent。
- 只引用已有或计划中明确要创建的检查；不要宣称会运行未验证、未授权或不存在的命令。
- 任务没有 Harness 契约、证据或不适用说明时，不能标记为 `done`。
