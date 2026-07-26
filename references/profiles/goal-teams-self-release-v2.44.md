---
type: Goal Teams Policy Profile
title: Goal Teams Self Release V2.44
description: 仅用于 Goal Teams 仓库 V2.44 自发布的测试能力、工程指标、发行状态机、流程澄清与公开归档规则。
tags: [goal-teams, self-release, v2.44, policy-profile, testing, benchmark, release-lifecycle]
timestamp: 2026-07-23T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Self Release V2.44

> V2.45 起本 Profile 仅用于历史 replay；任何 external write 都必须 fail closed。

机器名：`goal-teams-self-release-v2.44`。本 Profile 只适用于可信 adapter 已验证目标为 Goal Teams 仓库、产品版本为 `V2.44` 且任务类型为 `goal_teams_self_release` 的任务。V2.43/V2.42/V2.41/V2.40/V2.39/V2.38 Profile 仅用于历史 replay。

## 身份、流程与版本投影

1. `VERSION` 是当前产品版本唯一文本源；核心策略固定 `V2.5`，legacy schema 固定 `V2.3`。
2. 启动先按 `references/flow-clarification-protocol.md` 提出小、中、大流程；用户确认前不得建立正式 Plan、Teams 或成员派发。自发布的可信 route 仍按事实派生 Full/Regulated，用户不能以小/中流程降低安全、发行或独立审计门。
3. README 的当前版本投影以用户确认的 README 内容为准；当前 GitHub Release 资产仍按 `release/current/` 的已发布版本校验，二者不得被混同为已完成的 GitHub Release。
4. `candidate` 要求 VERSION、SKILL、当前 Profile、prompt manifest 与候选身份一致；`stable` 只能由独立 live auditor 重建 main/tag/Latest/asset/install/README/CI 事实。

## V2.44 API 与 E2E 测试能力

1. `references/testing-capability-manifest.json` 是七个评分维度、固定 100 分权重、append-only 已知问题集合和反游戏规则的机器 SSOT；问题数量随 LOOP 发现追加，不得把静态计数当成验收口径。
2. `references/testing-capability-protocol.md` 定义 `integration-test-plan`、V2.44 `test-case` 和 `test-run-result` 三类交接物，以及 API/E2E 风险分母、问题账本、真实行为 Benchmark 和完成边界。
3. V2.44 的测试文件引用必须绑定 path、SHA-256 和 discovery；缺文件、digest drift、`not_run`、`blocked`、`unavailable`、只返回退出码或只提供 prose 均不得计入满分。
4. 测试设计、执行、Review 和 Completion Audit 使用不同 run identity；retry 通过不能隐藏首次失败，flake、cleanup 和 replay 必须保留。
5. 未来新发现的问题必须追加稳定 issue event 并关联评分维度；不得删除问题、降低阈值或改写 seeded defect 预期以取得满分。

## V2.43 工程指标兼容

1. V2.44 继续使用 `goal-teams-engineering-metrics-v2.43` sidecar、manifest 和 deterministic calculator；产品版本升级不改写历史指标 schema。
2. `pending`、`unavailable`、`not_applicable`、`insufficient_sample` 不得写成零；DER/RRR/ARCR 未关闭观察窗时不得声称 final。
3. 工程指标是观测面，不替代 SPEC、Harness、Evidence、Review、测试或 Completion Audit，也不自动成为测试能力分数。

## 发行与完成边界

1. V2.40 的 CP00–CP18 发行状态机、受保护 Git tree snapshot、route receipt、宿主 attestation、Cache Evidence 和公开扫描规则继续适用，V2.44 不得弱化其 fail-closed 语义。
2. V2.44 历史发行身份由 `scripts/release/release_config.py` 和 `references/release-profiles/v2.44.json` 的已提交 blob 冻结，并流入 replay scope、每个 operation intent、CP05 approval 与 CP10 seal；调用者不能自选版本、candidate、tag、Release 文本、baseline 或 close schema。V2.44/V2.40 profile 都只允许 replay，external write 必须在 orchestrator 与 GitHub adapter 双边拒绝。
3. V2.44 snapshot 继续使用 sealed source-commit authority、唯一 generated OKF 和严格四列 `_files.sha256`；产品版本变化不得触发两列 legacy 格式或缺失 mode/size。
4. 固定 52 条 `ASSERT-V234-*`、iteration 9 隔离候选、iteration 11 delivery 边界、四维评分与独立审计继续保留；评分、cache 与工程指标不能覆盖测试、Evidence、Review 或 Audit 失败。
5. 每份适用 Architecture Design 必须内嵌 Development Configuration Plan 与 Production Configuration Plan；不得记录 secret 值，生产配置规划不代表部署授权。
6. CP18 公开归档仅接收 `docs/archive/releases/V2.44/` 下经 sanitizer 处理的完成文档；不得出现 invocation、transport handle、绝对路径、raw log、secret 或 private provenance。
7. CP05 是 repository-external trusted-host transaction：public `promote/recover`
   与 candidate 私有 workflow approval helper 对 V2.44 都必须返回
   `E_V244_HOST_CP05_REQUIRED`，不得接受 hash/path/env/argv/file token。宿主在
   Reviewer 后重验冻结身份、HMAC/TTL/challenge replay 与两项 intent，单次 CAS
   推进 CP05，并把完整 signed host acceptance digest 写入状态 receipt chain。
   Reviewer 必须从仓库外空目录启动且不得加载候选 `AGENTS.md`；宿主必须固定
   Git/Node/Codex provenance，并将 V2.44 current route receipt 摘要、policy、
   candidate/base 投影到 signed host acceptance。acceptance 必须使用发行 Profile
   中冻结的 Ed25519 公钥独立验签；`key_id` 是原始 32-byte 公钥的 SHA-256，
   签名消息是固定版本域
   `goal-teams/v2.44/cp05/host-acceptance/ed25519/v1`、一个 NUL byte 与移除
   `signature` 后对象的 canonical JSON bytes 的顺序拼接。HMAC 只允许保护
   宿主私有 challenge state，不得充当候选侧可伪造的公开验收证明。

## 兼容边界

Portable Core 可由不同 Agent runtime 采用；完成、发行和独立 acceptance 仍只能由能力合同已证明的 adapter 执行。缺少 command execution、vcs snapshot、独立成员、真实 API/E2E 行为环境或 host identity attestation 时，必须保持 `blocked|not_run|unavailable`，不能写 `accepted`、`achieved` 或计入对应满分。
