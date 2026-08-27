---
type: Goal Teams Function Rules
title: Testing Function
description: 定义风险分母、适用测试、执行与两阶段测试策略。
tags: [goal-teams, v2.66, testing, tdd, release]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Testing Function

- `function_id`: `FUNCTION-TESTING-V250`
- `purpose`: 拥有风险分母、适用测试类型、执行、缺陷闭环和 Development/Release 两阶段测试策略。

## trigger_and_exclusion_facts

- 触发：Current route 需要验证行为、集成、UI、数据、迁移、性能、安全或发行候选。
- 排除：UI 像素算法、具体发行步骤和授权语义不在本文件定义。

## inputs

- Requirement、AC、API、persona、state、dependency、failure mode、journey、data、authorization 和变更影响。
- workflow phase、source/environment identity 和适用测试类型。

## obligations_and_outputs

- 分别建立 Development denominator 与 Release denominator；二者不能互相替代。
- 产生 `RiskDenominator → TestCase → TestRunReceipt → TestReviewReceipt` digest chain。
- Development 只阻断 TDD 与受影响面增量；Release Readiness 对冻结候选执行一次新全量回归和集中安全审核。
- TestCase、测试文件、source、Git baseline 与结果通过 digest/receipt 绑定；手写变更清单不能替代 Git 自动采集的真实差异。

## oracles_and_evidence

- 每项分母都有来源、严重度、适用性、case/assertion/check 映射与 coverage state。
- 每条 assertion 有业务 Oracle 与 observed result；discovery 必须大于零，exit/status-only 不能通过。
- failed、blocked、not_run、flaky 项保留在适用分母中。

## contract_refs

- `CONTRACT-TEST-CASE-GATE-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`
- `CONTRACT-REVIEW-COMPLETION-V250`

## dependencies

- `FUNCTION-REQUIREMENTS-V250`
- `CORE-V250`

## owned_rule_ids

- `GT250-TEST-DENOMINATOR`: 风险分母必须完整、revision-bound 且 digest-bound；N/A 需要影响分析与适用接受，未覆盖项不得消失。
- `GT250-TEST-PHASES`: Medium/Large 使用互不混用的 Development 与 Release denominator；Release denominator 可预计算但不得计入开发完成。
- `GT250-TEST-DEVELOPMENT`: Development 阻断 Gate 只有适用 TDD 和 affected-scope incremental；关键 P0 journey 作为分母 case，不是第三个独立 Gate。
- `GT250-TEST-RELEASE`: 只有 `implementation_scope_complete=true` 且可信 `release_intent=true` 才对冻结候选执行一次新的 final full regression 与 release security review。
- `GT250-TEST-ORACLE`: 每条 required assertion 必须同时存在业务 Oracle、observed result 和当前 Evidence；仅命令退出码、状态字段或说明不能通过。
- `GT250-TEST-DEFECT`: 首个失败、attempt、flake 判定、修复和重验证必须追加记录；重试不得覆盖原失败。
- `GT250-TEST-COVERAGE`: passed numerator 只计入 requirement/check/run passed、Evidence valid/current 且 revalidation closed 的适用项；not_required 不贡献 passed。
- `GT263-TEST-FIXED-REGRESSION`: affected-scope、fixed regression 与独立审计分别形成当前回执；测试或 source binding 漂移必须重验，不能以额外审计无限扩展修复范围。
- `GT263-TEST-BLOCKED-TRUTH`: 环境、外部依赖或可信 Evidence 不可用时，`blocked|not_run` 是合规结果；不得降低 Oracle、删除分母项或改写为 PASS。
