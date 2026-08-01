---
type: Goal Teams Policy Profile
title: Goal Teams Self Release V2.36
description: 只用于 Goal Teams 仓库 V2.36 自发布的附加断言、恢复、评分与公开归档协议。
tags: [goal-teams, self-release, v2.36, policy-profile, okf]
timestamp: 2026-07-12T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Self Release V2.36

机器名：`goal-teams-self-release-v2.36`。

本 Profile 扩展 `goal-teams-core-v2.5`，只适用于可信 adapter 已验证目标仓库为 Goal Teams、产品版本为 `V2.36` 且任务类型为 `goal_teams_self_release` 的发布任务。普通业务项目、普通 Goal Teams 使用、仓库内非发布维护都不得加载本文件或继承其固定轮次和归档布局。

## 派生与隔离

- runtime 从 `product_version + verified target repository + task_type` 派生本机器名；`state_gate_profile` 省略时自动填充，显式提供时必须与派生值完全一致，否则 fail closed。
- `verified target repository` 由已接受 V2.35 基线 `c91e33737cc13c68bb5cb34c572fa05e7849f1e4` 的 Git ancestry 与基线 `SKILL.md` 身份证明，不读取候选 worktree 中可变的 `VERSION`/`SKILL.md` 作信任根。
- 任一事实缺失或冲突时保持 `goal-teams-core-v2.5` 或 blocked，不得根据文件名、自由文本或调用方自报静默升级/降级。
- 本 Profile 的 52 条 `ASSERT-V234-*` 是 Goal Teams 自发布 Harness 的兼容断言集，不改写 V2.5 通用完成谓词。

## 自发布控制平面

1. current contract 必须冻结恰好 52 条自发布断言，并绑定独立 review、版本、candidate tree 与 Evidence。
2. 可恢复状态使用同一版本目录下的 `feature_list.json`、`progress.md`、`contract.md`、`log.md`；marker-last、CAS、journal、hash-chain 与 reconcile 规则保持 fail closed。
3. 自发布门序为：delta contract review -> Architecture accepted -> Environment ready -> independent tests/current TDD red -> implementation -> independent green/full regression -> protected complete Git snapshot -> release readiness -> remote/local release Evidence -> independent post-release task -> graph-external Completion Audit。
4. 上述控制平面只声明会话内/磁盘恢复，不代表 daemon、后台 runner、CI/CD 或生产审批。
5. candidate/Evidence 只接受 `v236-snapshot-create` 自动发现的完整 Git 变更集，不接受人工 `source_paths`；宿主签名 route receipt 必须证明实际目标为 Goal Teams 仓库、`release=true`、派生 self-release Profile、Full/Regulated execution contract 与完整 gates，并把 trusted release base 绑定 snapshot baseline。Review、测试与 Audit 的独立身份使用宿主私有 challenge state 跨调用防重放，仅不同自报 run ID 或无 state 的诊断验证不足以通过。
6. 候选仓库中的 `completion-audit` 没有 V2.36 成功分支；CLI、Python 调用或调用方自选 context 均必须返回 `E_V236_HOST_ADAPTER_REQUIRED`。仓库外宿主冻结包含 TaskList、Evidence/Review 引用日志、报告和 artifact 的完整验收输入树后，在自己的受信进程内验证 route request/receipt、protected snapshot、attested identity registry 与完整/core binding，并仅在全部门通过时消费私有 challenge state。省略 `state_gate_profile`、route receipt 或 trust 输入都不得回退 legacy 门禁。

## 固定第 9/11 轮

- iteration 9 `Reason -> Act` 前执行一次 `controlled_reset`：只允许把 contract 预授权、位于 `.goalteams-candidates/<candidate_id>` 且绑定 current tree digest 的 disposable candidate 原子移入 `.goalteams-quarantine/<reset_id>/<candidate_id>` 并保留 receipt。禁止删除仓库、工作树、用户数据、ledger、Evidence、Review、Audit 或 provenance；purge 需要新的破坏性授权。
- iteration 10 只能从 reset receipt 绑定的 clean candidate 重建。
- iteration 11 是此 Profile 唯一 delivery/`achieved` 写入边界；required tasks/checks、current Evidence/Review、四文件一致、reset lineage、受保护 Git tree snapshot、全量测试、评分/诊断、归档预检和独立 Completion Audit 必须全部通过。失败保持 `partial|blocked` 并允许修复/重验，不得写 achieved、公开归档或进入 iteration 12。

## 评分与诊断

- `design|originality|craft|functionality` 四维各恰好四个冻结 rubric item，每项通过计 `0.25`；分数必须从 current Evidence 重算并绑定不同 reviewer run。
- `unverified` 计 0；评分只是自发布质量信号，不能覆盖测试、Harness、Review、安全或 Audit 失败。
- GTLOG divergence、prompt lifecycle 与 moving bottleneck 使用自发布 runtime 的确定性规则；原始 provenance 不得删除或重写。

## 公开归档

- 只有 sanitizer 后的 completed/public 普通文件可进入 `docs/archive/V2.36/<delivery_id>/`；公开面不得包含 invocation/tool-call、transport handle、绝对路径、raw log、secret 或 private provenance。
- `GoalTeamsWork-*`、`.goalteams-state/`、`.goalteams-candidates/`、`.goalteams-quarantine/`、Member Goal Packet 和私有审计链不得进入公开 package/archive/commit。
- 本地 ledger/Evidence/Review/Audit/provenance 保留完整 source/hash/identity 绑定；清除调用痕迹只能生成公开副本，不能原地修改或删除审计源。
