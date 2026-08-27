---
type: Goal Teams Functional Contract
title: Test Case Gate Contract
description: 定义风险分母、不可变测试用例、真实运行与复核的门禁合同。
tags: [goal-teams, v2.66, testing, gate, tdd]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Test Case Gate Contract

- `contract_id`: `CONTRACT-TEST-CASE-GATE-V250`
- `purpose`: 定义测试分母、不可变用例、真实运行和独立复核的 digest chain 与统一 Gate 生命周期。

## trigger_and_exclusion_facts

- 触发：route 派生任意测试或验证 Gate。
- 排除：`gate_requirement=not_required` 不创建执行 Receipt，也不计入 passed numerator。

## inputs

- phase-specific RiskDenominator、TestCase、source/test/environment identity、runner 和 validator identity。

## obligations_and_outputs

- 四对象共享 exact denominator identity/digest，并按角色只保存相关 item refs。
- TDD red 与 green 使用同一 case/test-file digest、不同 source digest 和不同 run digest。
- Gate requirement、check、run、Evidence 和 revalidation 分轴记录。

## oracles_and_evidence

- digest 重算、case immutability、真实 discovery、assertion observed result、coverage diff 和 reviewer receipt。

## contract_refs

- `CONTRACT-HARNESS-EVIDENCE-V250`
- `CONTRACT-REVIEW-COMPLETION-V250`

## dependencies

- `CORE-V250`

## owned_rule_ids

- `GT250-TESTCASE-CHAIN`: `RiskDenominator.digest → TestCase.digest → TestRunReceipt.digest → TestReviewReceipt.digest` 不可替换，Review 禁止跨 Run digest 复用。
- `GT250-TESTCASE-IMMUTABLE`: TestCase 的输入、处理、期望输出、assertions 或 test-file digest 变化必须生成新 ID/revision/digest。
- `GT250-TESTCASE-TDD`: TDD red 必须在实现前按预期失败，green 必须在变更后通过；二者绑定同一 case/test file，source 与 receipt digest 必须不同。
- `GT250-TESTCASE-GATE-STATE`: Gate 使用 `required|conditional|not_required`；required 只有 check/run passed、Evidence valid/current 且 revalidation closed 才通过。
- `GT250-TESTCASE-NOT-REQUIRED`: not_required 必须有结构化理由，不创建 Run Receipt，不贡献 passed，也不能被 failed/blocked/waived 替代。
- `GT250-TESTCASE-REVIEW`: TestReviewReceipt 必须重算断言、核对 coverage diff、validator identity 和 actor assurance；只采信当前 Run digest。
