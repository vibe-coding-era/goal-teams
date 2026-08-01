---
type: Goal Teams Policy Profile
title: Goal Teams Self Release V2.49
description: Goal Teams V2.49 的 Current/Replay 隔离、两阶段测试门禁与简化 Skill 发行规则。
tags: [goal-teams, self-release, v2.49, policy-profile]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Self Release V2.49

机器名：`goal-teams-self-release-v2.49`。该 Profile 只在 V2.49 Current generation、
可信 route receipt 和 `goal_teams_self_release` 共同命中时加载。V2.48 及更早发行规则只能由
显式 Replay route 加载，不能进入 V2.49 默认闭包。

## 两阶段门禁

1. Development 阶段只要求 TDD 与受影响面增量验证；正式 S0–S4、全量回归、集中安全审核和安装演练均为 `not_required/not_run`。
2. 只有 `workflow_phase=release`、`release_intent=true`、`implementation_scope_complete=true`、`stage=released` 时进入 Release Readiness。
3. S1 对 exact released commit/tree 各执行一次 `full_regression` 和独立 `release_security_review`，两者必须 `passed/current`。
4. S2 对每个 exact asset set 只在仓库 `release/versions` 构建一次；不执行第二次确定性构建、逐字节复现比较或 S2 仓库安全检查，也不据此声明可复现性或安全性。
5. `repository_boundary_compliance` 在 S2 后立即执行，是 S0–S4 之外的独立只读门禁；它绑定 released commit/tree、同一 asset set、package manifest、validator、argv 和 cwd。首次 receipt 标记 `executed_now`；恢复时标记 `reused_receipt`，但进入后续门禁前仍必须现场重验 clean/frozen source 与同一 asset set。
6. S3 仅在 Large Release、S1 `passed/current` 且 repository boundary current 后，对 exact S2 asset set 执行一次；`INSTALL_REPORT` 必须位于本次隔离 `CODEX_HOME` 内。Small、Medium 和非 Release 均为 `not_required/not_run`，进程调用数为零。
7. Workflow 的 S4 步骤只生成 `authorized_operation_plan`，外部写入调用数为零；正式执行与 exact readback 必须作为后续独立事实记录，不得把计划写成已发布。
8. 跨 job 续接只允许使用绑定 exact released SHA 的官方 Actions artifact；其中封存 `release/versions/V2.49` 的同一四资产及 S1/S2/integrity/boundary/S3/release-control/plan receipts。后续 S4 必须下载回同一 release root，重建调用数为零。

## Authorization、transport 与 runtime

- S4 复用项目开始时唯一的 `project_start_authorization_receipt`，保持 authorization lineage；不新增过程确认或 exact-value 再授权。
- 操作者的 Git fetch/push remote 必须是 GitHub SSH；HTTPS remote 或隐式 HTTPS fallback 均 fail closed。PR、Actions/ruleset 回读和 GitHub Release 使用 `gh` API/CLI，不把 Git payload 改走 HTTPS。
- candidate transition receipt 只能支撑 cutover/incremental，不能进入 S0。正式 S0 前必须由 candidate 外的 fresh process 读取 exact released inputs。
- 本地 ignored Codex host adapter 只提供 `actor_assurance=I1`、`actor_relationship=correlated` 的加载证明；它不得宣称 external independence、cryptographic attestation 或独立最终验收。

## 用户可见输出

固定输出 `任务、成员、进度、结果、Banchmark`，并按 Loop Decision 恰好二选一输出
`下一轮 LOOP` 或 `下一个任务`。不得输出合并字段、额外一级字段或内部推理过程。
