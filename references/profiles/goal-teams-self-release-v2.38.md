---
type: Goal Teams Policy Profile
title: Goal Teams Self Release V2.38
description: 只用于 Goal Teams 仓库 V2.38 自发布的附加断言、恢复、评分、prompt cache identity 与公开归档协议。
tags: [goal-teams, self-release, v2.38, policy-profile, prompt-cache, okf]
timestamp: 2026-07-13T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Self Release V2.38

机器名：`goal-teams-self-release-v2.38`。

本 Profile 扩展 `goal-teams-core-v2.5`，只适用于可信 adapter 已验证目标仓库为 Goal Teams、产品版本为 `V2.38` 且任务类型为 `goal_teams_self_release` 的发布任务。普通业务项目、普通 Goal Teams 使用、仓库内非发布维护都不得加载本文件或继承其固定轮次和归档布局。

## 派生与隔离

- runtime 从 `product_version + verified target repository + task_type` 派生本机器名；任一事实缺失或冲突时保持 Core 或 blocked。
- 自发布仍以已接受 release base、受保护 Git tree snapshot、host route receipt 和宿主 attested identity 为信任边界，候选 worktree 的可变 VERSION/SKILL 不构成信任根。
- 52 条 `ASSERT-V234-*` 继续作为自发布兼容断言集，不得成为普通项目的全局完成条件。

## V2.38 Prompt Identity Gate

1. `references/prompt-cache-manifest.json` 是 runtime prompt 顺序和 route byte budget 的机器 SSOT。
2. 自发布候选必须记录 `prefix_manifest_sha256`、`route_static_digest`、ordered refs、budget receipt 与 route bytes；最终 prompt 不可见时 `runtime_prompt_digest=null`，且与完整 `skill_tree_digest` 分离。
3. repository startup 必须把 `.agents/skills/goal-teams/SKILL.md` 纳入 12,032-byte 门禁，不允许遗漏 wrapper 形成 false green。
4. benchmark observer telemetry 与 subject-visible telemetry 必须分离；cached token share 不得命名为 request hit rate，也不得影响 release eligibility。
5. 缺少 live provider usage 不阻止确定性结构发布门，但必须将 cache 性能结论标为 unavailable，禁止伪造或外推。

## 自发布控制平面

1. current contract 冻结恰好 52 条自发布断言，并绑定独立 review、版本、candidate tree 与 Evidence。
2. 可恢复状态继续使用 `feature_list.json`、`progress.md`、`contract.md`、`log.md`；marker-last、CAS、journal、hash-chain 与 reconcile fail closed。
3. 门序保持 contract review → Architecture → Environment → independent tests → implementation → independent green/full regression → protected snapshot → release readiness → remote/local Evidence → post-release task → graph-external Completion Audit。
4. 候选 runtime 不提供 Python/CLI 自签完成入口；缺可信宿主验收时返回 `E_V236_HOST_ADAPTER_REQUIRED`。

## 固定第 9/11 轮

- iteration 9 只允许隔离 contract 预授权且绑定 current tree digest 的 disposable candidate；禁止删除仓库、工作树、用户数据、ledger、Evidence、Review、Audit 或 provenance。
- iteration 10 只能从 reset receipt 绑定的 clean candidate 重建。
- iteration 11 是唯一 delivery/`achieved` 写入边界；required tasks/checks、current Evidence/Review、四文件一致、reset lineage、受保护 snapshot、全量测试、prompt identity、归档预检和独立 Audit 必须全部通过。

## 评分、公开归档与失败语义

- `design|originality|craft|functionality` 四维各四个冻结 rubric item，每项 `0.25`；评分不能覆盖测试、Harness、Review、安全或 Audit 失败。
- 只有 sanitizer 后的 completed/public 普通文件可进入 `docs/archive/V2.38/<delivery_id>/`；公开面不得包含 invocation、tool-call、transport handle、绝对路径、raw log、secret 或 private provenance。
- `GoalTeamsWork-*`、`.goalteams-state/`、Member Goal Packet 与私有审计链不得进入公开 package/archive/commit。
- prompt cache 未命中、遥测 unavailable 或 A/B probe 未执行只影响 cache 性能结论；结构、行为、分发或安全门失败仍按原门禁 fail closed。
