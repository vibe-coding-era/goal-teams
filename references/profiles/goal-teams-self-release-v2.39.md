---
type: Goal Teams Policy Profile
title: Goal Teams Self Release V2.39
description: 只用于 Goal Teams 仓库 V2.39 自发布的附加断言、恢复、评分、Cache Evidence、Google OKF 与公开归档协议。
tags: [goal-teams, self-release, v2.39, policy-profile, prompt-cache, okf]
timestamp: 2026-07-13T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Self Release V2.39

机器名：`goal-teams-self-release-v2.39`。

本 Profile 扩展 `goal-teams-core-v2.5`，只适用于可信 adapter 已验证目标仓库为 Goal Teams、产品版本为 `V2.39` 且任务类型为 `goal_teams_self_release` 的发布任务。普通业务项目、普通 Goal Teams 使用、仓库内非发布维护都不得加载本文件或继承其固定轮次和归档布局。`goal-teams-self-release-v2.38` 只用于历史对象的只读 replay，不得成为当前 route。

## 派生与隔离

- runtime 从 `product_version + verified target repository + task_type` 派生本机器名；任一事实缺失或冲突时保持 Core 或 blocked。
- 自发布仍以已接受 release base、受保护 Git tree snapshot、host route receipt 和宿主 attested identity 为信任边界，候选 worktree 的可变 VERSION/SKILL 不构成信任根。
- 52 条 `ASSERT-V234-*` 继续作为自发布兼容断言集，不得成为普通项目的全局完成条件。

## V2.39 Prompt Identity 与 Cache Evidence Gate

1. `references/prompt-cache-manifest.json` 是 runtime prompt 顺序和 route byte budget 的机器 SSOT；当前 self-release route 必须指向本 Profile，V2.38 Profile 只允许出现在 replay route。
2. 自发布候选必须记录 `prefix_manifest_sha256`、`route_static_digest`、ordered refs、budget receipt 与 route bytes；最终 prompt 不可见时 `runtime_prompt_digest=null`，且与完整 `skill_tree_digest` 分离。
3. repository startup 必须把 `.agents/skills/goal-teams/SKILL.md` 纳入 12,032-byte 门禁，不允许遗漏 wrapper 形成 false green。
4. Production Evidence 只能由可信 capability receipt、host-observed ordered manifest、registered attestation verifier、原始 usage artifact 与确定性 normalize/aggregate receipt 链支撑；synthetic fixture 不能升级为 live Evidence。
5. benchmark observer telemetry 与 subject-visible telemetry 必须分离；cached token share 不得命名为 request hit rate，也不得影响 release eligibility。
6. 当前发行状态必须按 canonical 四个正交轴报告：`structural_delivery_state=passed`、`host_integration_state=unavailable`、`live_cache_validation_state=not_authorized`、`request_hit_rate_support_state=unavailable`。各项以实际 Evidence 为准更新，任一不可用都不得被单一 `achieved` 覆盖。
7. 本版本只允许 `claim_scope=structural_governance`；缺少 provider、网络、账号、费用授权或可信 request 语义时，不得声称 live cache optimization、provider hit 或 request hit rate。

## Google OKF 与发行边界

1. 当前 tracked/package Markdown 必须由 `references/okf-conformance-policy.json` 唯一分类为 A/B/C；未知、重叠、unsafe YAML、identity/hash 漂移均 fail closed。
2. source tracked、package selection、staged/tarball 与 installed tree 四个边界都必须拒绝 `docs/`、`develops/`、`GoalTeamsWork-*` 和未授权过程产物。
3. canonical OKF manifest 只能在冻结的 install/release package 上生成，并由外部 install/release identity 绑定；repository preview 或 manifest subset 不得冒充 package-complete。
4. GitHub Release 只能消费 `release/versions/V2.39/` 中已经本地校验且 hash 闭合的资产。

## 自发布控制平面

1. current contract 冻结恰好 52 条自发布断言，并绑定独立 review、版本、candidate tree 与 Evidence。
2. 可恢复状态继续使用 `feature_list.json`、`progress.md`、`contract.md`、`log.md`；marker-last、CAS、journal、hash-chain 与 reconcile fail closed。
3. 门序保持 contract review → Architecture → Environment → independent tests → implementation → independent green/full regression → protected snapshot → release readiness → remote/local Evidence → post-release task → graph-external Completion Audit。
4. 候选 runtime 不提供 Python/CLI 自签完成入口；缺可信宿主验收时返回 `E_V236_HOST_ADAPTER_REQUIRED`。

## 固定第 9/11 轮

- iteration 9 只允许隔离 contract 预授权且绑定 current tree digest 的 disposable candidate；禁止删除仓库、工作树、用户数据、ledger、Evidence、Review、Audit 或 provenance。
- iteration 10 只能从 reset receipt 绑定的 clean candidate 重建。
- iteration 11 是唯一 delivery/`achieved` 写入边界；required tasks/checks、current Evidence/Review、四文件一致、reset lineage、受保护 snapshot、全量测试、prompt identity、OKF/package gate、归档预检和独立 Audit 必须全部通过。

## 评分、公开归档与失败语义

- `design|originality|craft|functionality` 四维各四个冻结 rubric item，每项 `0.25`；评分不能覆盖测试、Harness、Review、安全、OKF 或 Audit 失败。
- 只有 sanitizer 后的 completed/public 普通文件可进入 `docs/archive/V2.39/<delivery_id>/`；公开面不得包含 invocation、tool-call、transport handle、绝对路径、raw log、secret 或 private provenance。
- `GoalTeamsWork-*`、`.goalteams-state/`、Member Goal Packet 与私有审计链不得进入公开 package/archive/commit。
- prompt cache 未命中、遥测 unavailable 或 live probe 未获授权只影响 cache 性能结论；结构、行为、分发或安全门失败仍按原门禁 fail closed。
