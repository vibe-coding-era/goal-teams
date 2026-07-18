---
type: Goal Teams Policy Profile
title: Goal Teams Self Release V2.40
description: 只用于 Goal Teams 仓库 V2.40 自发布的附加断言、可恢复发行状态机、公开身份、Cache Evidence、Google OKF 与归档协议。
tags: [goal-teams, self-release, v2.40, policy-profile, release-lifecycle, prompt-cache, okf]
timestamp: 2026-07-14T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Self Release V2.40

机器名：`goal-teams-self-release-v2.40`。

本 Profile 扩展 `goal-teams-core-v2.5`，只适用于可信 adapter 已验证目标仓库为 Goal Teams、产品版本为 `V2.40` 且任务类型为 `goal_teams_self_release` 的发布任务。普通业务项目、普通 Goal Teams 使用、仓库内非发布维护都不得加载本文件。`goal-teams-self-release-v2.39` 与 `goal-teams-self-release-v2.38` 只用于历史对象的只读 replay，不得成为当前 route。

## 派生与隔离

- runtime 从 `product_version + verified target repository + task_type` 派生本机器名；任一事实缺失或冲突时保持 Core 或 blocked。
- 自发布以已接受 release base、冻结 candidate commit、受保护 Git tree snapshot、current route receipt、GitHub live authority 和宿主 attested identity 为信任边界；可变工作树中的 VERSION/SKILL 或本地 success 布尔值不是完成事实源。
- 52 条 `ASSERT-V234-*` 继续作为自发布兼容断言集，不得成为普通项目的全局完成条件。

## V2.40 公开身份与版本投影

1. `VERSION` 是当前产品版本的唯一文本源；核心策略固定为 `V2.5`，legacy 机器数据 schema 固定为 `V2.3`，三者不得混写。
2. 两个根 README 各自必须恰好包含一个 `goal-teams-release` 受控 marker 块，且版本、`v2.40` tag 链接和 `release/current/README.md` 链接完全一致；marker 外用户正文不得被发行器重写。
3. `development` 允许候选 runtime/Profile 为 V2.40，但 README/current 仍投影经明确输入的上一 published version；不得宣称候选已发布。
4. `candidate` 要求 VERSION、SKILL、当前 Profile、双语 README marker、`release/current` note/manifest 和候选身份全部为 V2.40。
5. `stable` 不由本地 checker 或 promote state 决定；只能由独立 auditor live 重建 main/tag/Latest/asset/install/README/CI 事实后判定。

## CP00–CP18 发行状态机

1. 每个 checkpoint 与非幂等 operation 都先写 intent、expected-before 与 idempotency identity，执行后 live readback，最后写 marker；本地 state 只用于恢复提示。
2. CP12 仅推送冻结 candidate commit；CP13 只接受绑定 exact head SHA、approved workflow blob/checker 与固定 required jobs 的成功 CI。
3. CP14 创建覆盖 main 更新路径的 active remote promotion lock，并重新验证与 CP03 完全一致的 GitHub actor、repository、admin permission、API capability 与授权动作。
4. CP15 只创建或采纳绑定 candidate 的 annotated `v2.40` tag，different 永久 conflict；tag ruleset 禁止 update/deletion。
5. CP16 创建或恢复 Draft，上传并重新下载固定四资产，只在临时 `CODEX_HOME` 进行 remote-bundle rehearsal。
6. CP17 的唯一顺序是 `main_promote -> release_publish -> published_asset_download -> actual_install -> post_release_ci -> independent_audit`。main 先在 remote lock 内执行 exact compare-and-swap；只有 exact main 才可 publish 已验证 Draft。该 independent audit 只冻结 live 发行身份、安装、CI 与远端保护，不得包含 `GoalTeamsWork`/SSOT tree 或任何 candidate-supplied positive host authority。
7. CP17 通过到 CP18 `close` 之间是唯一合法 SSOT finalization window。外层 release host 必须在此窗口补齐并归档 required Evidence、accepted tasks 与独立 Completion；CP18 把最终 archive manifest 绑定到 exact CP17 audit SHA，调用 `_validate_archived_goal_teams_ssot`，并在永久保护写入前后重验同一完整关闭边界。`CP18.archive_close` exact readback 的 marker-loss 恢复也必须 fresh 重算，不能采纳漂移的 ledger/Completion/tree。`CLOSED` 只表示 distribution/archive closure，promotion state 与终态返回必须固定为 `goal_achieved=false`、`external_host_acceptance_required=true`、`completion_authority=repository_external_single_use_host`。候选侧 V2.36 `completion-audit` 仍须精确返回 `E_V236_HOST_ADAPTER_REQUIRED`，该拒绝证明 self-acceptance 边界保持 fail closed，不能被解释为 Completion 成功；Goal achieved 另需仓库外 single-use host acceptance。
8. 恢复只允许 `absent` 执行、prior-intent `exact` 采纳、`conflict` 停止、`unavailable` blocked；不得盲目重放、移动 tag、替换 candidate 或覆盖 published Release。

## Prompt Identity、Cache Evidence 与 telemetry

1. `references/prompt-cache-manifest.json` 保持 V2.38-compatible schema，是 runtime prompt 顺序、artifact compiler 与 route byte budget 的机器 SSOT；当前 self-release ordered refs 指向本 Profile。
2. Production Evidence 只能由可信 capability receipt、host-observed ordered manifest、registered attestation verifier、原始 usage artifact 与确定性 normalize/aggregate receipt 链支撑；synthetic fixture 不能升级为 live Evidence。
3. Cache Evidence 分别报告 structural、host、live-validation 与 request-hit-rate 四状态轴；cached token share 不得命名为 request hit rate，也不得影响 release eligibility。
4. Tokens 消耗或 Cache 命中率缺少可信宿主 usage Evidence 时必须分别写 `未获取到` / `Unavailable` 与 `null`，不得省略、估算、外推或写成 0。
5. 本版本只允许 `claim_scope=structural_governance`；缺少 provider、网络、账号、费用授权或可信 request 语义时，不得声称 live cache optimization、provider hit 或 request hit rate。

## Google OKF、打包与安装边界

1. 当前 tracked/package Markdown 必须由 `references/okf-conformance-policy.json` 唯一分类为 A/B/C；未知、重叠、unsafe YAML、identity/hash 漂移均 fail closed。
2. source tracked、package selection、staged/tarball 与 installed tree 四个边界都必须拒绝 `docs/`、`develops/`、`GoalTeamsWork-*` 和未授权过程产物。
3. GitHub Release 只能消费 `release/versions/V2.40/` 中已经本地校验、可复现且 hash 闭合的固定四资产。
4. actual install 只能消费重新下载并验证的 Published Release assets；Draft、本地 bundle 与 worktree 只能用于临时 rehearsal。

## 固定第 9/11 轮与完成边界

- iteration 9 只允许隔离 contract 预授权且绑定 current tree digest 的 disposable candidate；禁止删除仓库、工作树、用户数据、ledger、Evidence、Review、Audit 或 provenance。
- iteration 10 只能从 reset receipt 绑定的 clean candidate 重建。
- iteration 11 是唯一 delivery/`achieved` 写入边界；required tasks/checks、current Evidence/Review、四文件一致、reset lineage、冻结 candidate、全量测试、prompt identity、OKF/package gate、发行状态机、安装身份和独立 Audit 必须全部通过。

## 评分、公开归档与失败语义

- `design|originality|craft|functionality` 四维各四个冻结 rubric item，每项 `0.25`；评分不能覆盖测试、Harness、Review、安全、OKF、发行或 Audit 失败。
- CP18 唯一归档根是 `docs/archive/releases/V2.40/`；只有 sanitizer 后的 completed/public 普通文件可进入该目录，公开面不得包含 invocation、tool-call、transport handle、绝对路径、raw log、secret 或 private provenance。
- `GoalTeamsWork-*`、`.goalteams-state/`、Member Goal Packet 与私有审计链不得进入公开 package/archive/commit。
- telemetry unavailable 或 live probe 未获授权只影响性能结论；结构、行为、分发、安全或发行门失败仍按原门禁 fail closed。
