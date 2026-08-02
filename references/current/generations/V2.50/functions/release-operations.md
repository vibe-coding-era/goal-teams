---
type: Goal Teams Function Rules
title: Release Operations Function
description: 定义 Release Readiness、S0 至 S4、发行资产、发布与安装规则。
tags: [goal-teams, v2.50, release, github, install]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Release Operations Function

- `function_id`: `FUNCTION-RELEASE-OPERATIONS-V250`
- `purpose`: 拥有 Release Readiness、S0–S4、资产身份、GitHub/安装发布和正式回读。

## trigger_and_exclusion_facts

- 触发：可信 route 同时满足 `workflow_phase=release`、`release_intent=true` 和 `implementation_scope_complete=true`。
- 排除：候选、PR 开发、push、preview 或未来可能发行均不自动进入 Release Readiness。

## inputs

- frozen source commit/tree、依赖/config/migration、package manifest、release/test/security denominator、开始授权回执。

## obligations_and_outputs

- 固定顺序：freeze → 一次全量回归与集中安全审核 → 单次构建 → repository boundary gate → Large-only S3 → S4。
- S2 每个 exact released asset set 只构建一次并记录名称、大小和 SHA-256，不声明复现性或 S2 安全。
- S4 使用开始授权，通过 SSH Git transport 执行允许的提交、push、PR、tag、Release、上传、安装，并对每项外部效果 exact readback。

## oracles_and_evidence

- frozen identity、release Gate receipts、asset-set receipt、repository-boundary receipt、S3 receipt、SSH transport 和发布/readback receipts。

## contract_refs

- `CONTRACT-TEST-CASE-GATE-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`
- `CONTRACT-REVIEW-COMPLETION-V250`
- `CONTRACT-APPROVAL-SIDE-EFFECTS-V250`

## dependencies

- `FUNCTION-TESTING-V250`
- `FUNCTION-AGENT-RUNTIME-V250`

## owned_rule_ids

- `GT250-RELEASE-ENTRY`: 只有实现范围完成、可信发行意图和 exact released identity 冻结后才能进入 S0/Release Readiness。
- `GT250-RELEASE-S1`: Medium/Large 对同一 frozen identity 各执行一次新的 final full regression 与 release security review；任一冻结输入变化使二者同时 stale。
- `GT250-RELEASE-S2`: 每个 exact released asset set 恰好一次构建；第二次确定性构建、复现比较和 S2 安全检查固定不执行。
- `GT250-RELEASE-BOUNDARY`: workspace boundary、package manifest 和 release validator 是 S0–S4 外独立硬门，只读运行一次，不贡献 S2 安全或复现结论。
- `GT250-RELEASE-S3`: S3 只对 Large Release 且当前 S1 passed 执行；Small/Medium、非 Release 或 S1 未通过时进程计数为零且 argv 为空。
- `GT250-RELEASE-S4`: S4 不重复索权；只能执行开始授权 action allowlist，并逐项回读 tag、Release、资产、远端分支、PR 和安装身份。
- `GT250-RELEASE-SSH`: GitHub Git transport 必须使用 SSH；HTTP(S) remote 或降级 transport 不得用于提交链发布。
- `GT250-RELEASE-REPAIR`: repair 产生新 commit/tree 或 asset set 时旧 Release/S2/S3 receipts 保持 stale，新身份重新执行适用一次性 Gate。
