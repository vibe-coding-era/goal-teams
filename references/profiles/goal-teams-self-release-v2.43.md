---
type: Goal Teams Policy Profile
title: Goal Teams Self Release V2.43
description: 仅用于 Goal Teams 仓库 V2.43 自发布的附加断言、工程指标、发行状态机、流程澄清与公开归档规则。
tags: [goal-teams, self-release, v2.43, policy-profile, engineering-metrics, release-lifecycle]
timestamp: 2026-07-22T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Self Release V2.43

机器名：`goal-teams-self-release-v2.43`。本 Profile 只适用于可信 adapter 已验证目标为 Goal Teams 仓库、产品版本为 `V2.43` 且任务类型为 `goal_teams_self_release` 的任务。V2.42/V2.41/V2.40/V2.39/V2.38 Profile 仅用于历史 replay。

## 身份、流程与版本投影

1. `VERSION` 是当前产品版本唯一文本源；核心策略固定 `V2.5`，legacy schema 固定 `V2.3`。
2. 启动先按 `references/flow-clarification-protocol.md` 提出小、中、大流程；用户确认前不得建立正式 Plan、Teams 或成员派发。自发布的可信 route 仍按事实派生 Full/Regulated，用户不能以小流程降低安全、发行或独立审计门。
3. README 的当前版本投影以用户确认的 README 内容为准；当前 GitHub Release 资产仍按 `release/current/` 的已发布版本校验，二者不得被混同为已完成的 GitHub Release。
4. `candidate` 仍要求 VERSION、SKILL、当前 Profile、prompt manifest、release/current 与候选身份一致；`stable` 只能由独立 live auditor 重建 main/tag/Latest/asset/install/README/CI 事实。

## V2.43 工程指标与用户报告

1. `references/engineering-metrics-manifest.json` 是 FPAR、LCC、HER、SAR、CPAC、DER、RRR、CWR、SDI、RFR、ARCR、MRT 的 ID、顺序、算法元数据和聚合语义机器 SSOT。
2. 普通任务、Benchmark、Completion 与用户报告必须复用同一 deterministic calculator，不得各自维护不同公式。
3. 任务完成后生成 OKF `metrics/engineering-metrics.md`，包含本次、上一次、近期平均值、十二项算法、状态、coverage、观察窗与 Evidence；最终用户回复只提供状态、可点击路径并提醒查看，不展开完整表格。
4. `pending`、`unavailable`、`not_applicable`、`insufficient_sample` 不得写成零；DER/RRR/ARCR 未关闭观察窗时不得声称 final。
5. 工程指标第一版仅为观测面，不替代 SPEC、Harness、Evidence、Review、测试或 Completion Audit，也不自动成为 Release Gate 分数。

## 发行与完成边界

1. V2.40 的 CP00–CP18 发行状态机、受保护 Git tree snapshot、route receipt、宿主 attestation、Cache Evidence 和公开扫描规则继续适用，V2.43 不得弱化其 fail-closed 语义。
2. 固定 52 条 `ASSERT-V234-*`、iteration 9 隔离候选、iteration 11 delivery 边界、四维评分与独立审计继续保留；评分、cache 与工程指标不能覆盖测试、Evidence、Review 或 Audit 失败。
3. 每份适用 Architecture Design 必须内嵌 Development Configuration Plan 与 Production Configuration Plan；不得记录 secret 值，生产配置规划不代表部署授权。
4. CP18 公开归档仅接收 `docs/archive/releases/V2.43/` 下经 sanitizer 处理的完成文档；不得出现 invocation、transport handle、绝对路径、raw log、secret 或 private provenance。

## 兼容边界

Portable Core 可由不同 Agent runtime 采用；完成、发行和独立 acceptance 仍只能由能力合同已证明的 adapter 执行。缺少 command execution、vcs snapshot、独立成员或 host identity attestation 时，必须 blocked，不能写 `accepted` 或 `achieved`。
