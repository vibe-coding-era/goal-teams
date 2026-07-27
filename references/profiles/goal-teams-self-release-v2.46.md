---
type: Goal Teams Policy Profile
title: Goal Teams Self Release V2.46
description: 仅用于 Goal Teams 仓库 V2.46 自发布的验证治理、发行状态机、测试兼容和公开归档规则。
tags: [goal-teams, self-release, v2.46, verification-governance, policy-profile]
timestamp: 2026-07-27T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Self Release V2.46

机器名：`goal-teams-self-release-v2.46`。仅当可信 adapter 验证目标为 Goal Teams 仓库、产品版本为 `V2.46` 且任务类型为 `goal_teams_self_release` 时加载；V2.45 及更早 Profile 仅用于历史 replay。

## 组合规则

1. 通用规则仍由 Core V2.5、legacy V2.3 ledger、V2.44 API/E2E 测试合同和 V2.45 Release Engineer 提供；本 Profile 不复制这些正文。
2. V2.46 验证治理唯一详细入口是 `references/verification-governance-protocol.md`，机器 SSOT 是其 manifest、`schemas/v2.46/verification-governance.schema.json` 和 validator。
3. 历史 Evidence 有效性与当前适用性正交；变更后先做逐项影响分析，未证明受影响的历史结果不得清零。全量回归是当前策略，不是历史作废。
4. 测试合同、Grill me 和对抗式测试按 Lite/Standard/Full/Regulated 条件路由；不得降低标准、删除失败项、缩小风险分母或把未验证写成通过。
5. Rust/Tauri/desktop 能力统一引用 `references/desktop-engineering-protocol.md` 及其 manifest/schema/validator；按能力事实派生 Rust L1、Tauri L2/L3、生产包 L4、replica 四维与 cross-platform tuple，不复制到本 Profile。

## 发行与完成

1. V2.40 的 CP00–CP18、sealed source commit、严格四列 `_files.sha256`、固定四公开资产和 V2.45 的两次可信宿主人类确认继续适用。
2. 当前 active 身份由 `scripts/release/release_config.py` 和 `references/release-profiles/v2.46.json` 的 Git-tracked blob 冻结；历史 profile 必须拒绝外部写。
3. 外部副作用必须先持久化 intent，再执行、精确回读并 CAS 提交；不确定结果只能 reconciliation/recovery。`accepted|released|closed` 仅由完成谓词、有效 Evidence 和独立审计推导。
4. 固定 52 条自发布断言、iteration 9 候选隔离、iteration 11 delivery gate 和四维评分继续保留；评分、cache、指标或旧 Evidence 不能覆盖当前失败、`blocked|not_run|partial|stale|retest_required`。
5. CP05 仍是 repository-external trusted-host transaction；候选仓库不得自签或自报 Reviewer。CP18 只归档 `docs/archive/releases/V2.46/` 下经 sanitizer 处理的 public completed 文件。

## 兼容与降级

V2.44 test contract、V2.43 metrics 与 V2.3 ledger 保持原 schema 身份。缺少命令执行、真实环境、独立成员、可信宿主或有效 Evidence 时，保持 `blocked|not_run|unavailable`，不得推导 `achieved`。
