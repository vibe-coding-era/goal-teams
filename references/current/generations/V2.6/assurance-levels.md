---
type: Goal Teams Assurance Rules
title: Goal Teams V2.6 Assurance Levels
description: 定义 Discussion、Lite、Standard、Full 与 Regulated 的最小保证边界。
tags: [goal-teams, v2.6, assurance, routing]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.6 Assurance Levels

- `function_id`: `ASSURANCE-V250`
- `purpose`: 定义 Discussion、Lite、Standard、Full、Regulated 的最小保证，不承载领域实现或历史版本规则。

## trigger_and_exclusion_facts

- 触发：Current route 已生成可信规模、风险、外部性与可逆性事实。
- 排除：等级不代替功能触发；Full/Regulated 不会让不适用的 Release 或 S3 Gate 自动执行。

## inputs

- route facts、影响面、失败后果、恢复能力、外部写入和合规要求。

## obligations_and_outputs

- 输出最小 Evidence 深度、检查者 assurance、required Gate 和人工 artifact 上限。
- 每个等级只加载其所需功能 Owner 与合同 Owner。

## oracles_and_evidence

- route fixture 与 compiled rule IDs。
- assurance 未被调用方降级，且不适用功能没有进入 closure。

## contract_refs

- `CONTRACT-HARNESS-EVIDENCE-V250`
- `CONTRACT-REVIEW-COMPLETION-V250`

## dependencies

- `CORE-V250`
- `ROUTING-V250`

## owned_rule_ids

- `GT250-ASSURE-DISCUSSION`: Discussion 只形成可追溯结论；不建立执行 Ledger、Harness、Audit 或执行 Gate。
- `GT250-ASSURE-LITE`: Lite 面向低风险、单一可逆影响面，使用一个最小 Receipt 和直接验证，不派生全量治理仪式。
- `GT250-ASSURE-STANDARD`: Standard 加载受影响功能、TDD/增量验证和适度独立复核，不加载未触发的领域或发行 Gate。
- `GT250-ASSURE-FULL`: Full 用于跨模块或高影响工作，要求完整适用分母、独立 review 与 completion audit，但仍服从阶段边界。
- `GT250-ASSURE-REGULATED`: Regulated 在 Full 上增加外部合规、强身份或不可逆副作用要求；缺少必要宿主能力时必须 blocked。
- `GT250-ASSURE-NONESCALATION`: assurance 等级只改变适用检查深度，不授予外部写入、发行、安装、凭证或安全敏感动作权限。
