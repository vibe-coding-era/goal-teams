---
type: Goal Teams Functional Contract
title: Harness and Evidence Contract
description: 定义规格、检查、真实观察与可复核 Evidence 的绑定合同。
tags: [goal-teams, v2.6, harness, evidence]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Harness and Evidence Contract

- `contract_id`: `CONTRACT-HARNESS-EVIDENCE-V250`
- `purpose`: 把规格、检查、真实观察、外部副作用和可复核 artifact 绑定成 Current Evidence。

## trigger_and_exclusion_facts

- 触发：任务需要以测试、命令、审查、运行时或外部回读支撑状态。
- 排除：说明文本、模拟器、自报结果、只含退出码或无 exact binding 的 artifact 不构成完成 Evidence。

## inputs

- SPEC/AC、Harness assertion、source/route/contract/environment identity、exact argv/cwd、actor 和 raw artifacts。

## obligations_and_outputs

- Harness 为每个 required item 定义可执行检查、业务 Oracle、观察方式和失败 artifact。
- Evidence 记录 first failure、attempts、原始 artifact digest、观察值、外部 readback 与 cleanup/reconciliation。

## oracles_and_evidence

- digest 重算、source 与 environment readback、业务 Oracle 比较、artifact 存在性和 freshness。

## contract_refs

- `CONTRACT-TASK-STATE-V250`
- `CONTRACT-TEST-CASE-GATE-V250`

## dependencies

- `CORE-V250`

## owned_rule_ids

- `GT250-HARNESS-ASSERTION`: 每个 required item 必须有可执行 assertion、业务 Oracle、observed-result extractor 和失败 artifact 位置。
- `GT250-HARNESS-EXECUTION`: Run Receipt 绑定 exact argv、cwd、source、test、environment、runner、attempts 和 raw artifact digest；discovery 必须大于零。
- `GT250-EVIDENCE-BINDING`: Current Evidence 必须绑定 exact source、route、contract、Harness、environment 和 actor；任一输入漂移立即 stale。
- `GT250-EVIDENCE-VALIDITY`: Evidence state 只能由完整性、真实性和 binding 校验派生；未执行为 not_run，无法执行为 blocked，执行失败为 failed，不可信才 invalid。
- `GT250-EVIDENCE-SIDE-EFFECT`: 外部副作用分别保留 intent、execute-once、exact readback、cleanup/cleanup verification、idempotency 或 reconciliation Evidence。
- `GT250-EVIDENCE-APPEND-ONLY`: 首个失败、重试、flake、修复和 revalidation 追加记录，不覆盖历史事实或降低分母。
