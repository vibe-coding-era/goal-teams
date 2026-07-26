---
type: Goal Teams Policy Profile
title: Goal Teams Self Release V2.45
description: 仅用于 Goal Teams 仓库 V2.45 自发布的独立 Release Engineer、测试兼容、工程指标、发行状态机与公开归档规则。
tags: [goal-teams, self-release, v2.45, release-engineer, policy-profile, release-lifecycle]
timestamp: 2026-07-27T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Self Release V2.45

机器名：`goal-teams-self-release-v2.45`。本 Profile 只适用于可信 adapter 已验证目标为 Goal Teams 仓库、产品版本为 `V2.45` 且任务类型为 `goal_teams_self_release` 的任务。V2.44/V2.43/V2.42/V2.41/V2.40/V2.39/V2.38 Profile 仅用于历史 replay。

## 身份、流程与版本投影

1. `VERSION` 是当前产品版本唯一文本源；核心策略固定 `V2.5`，legacy schema 固定 `V2.3`。
2. 启动先按 `references/flow-clarification-protocol.md` 提出小、中、大流程；自发布的可信 route 仍按事实派生 Full/Regulated，用户不能以较轻交互流程降低安全、发行或独立审计门。
3. `candidate` 要求 VERSION、SKILL、当前 Profile、prompt manifest、release profile、双语 README 与 `release/current` 一致；`stable` 只能由独立 live auditor 重建 main/tag/Latest/asset/install/README/CI 事实。
4. Release Engineer 只随安装包发布并支持显式加载，不加入主 `SKILL.md`、prompt-cache 主路由或正式成员派发流程。

## V2.45 Release Engineer

1. `prompts/members/release-engineer/INDEX.md` 是独立成员入口，按 references、kits 与 runtime 子文件渐进加载；普通调用只检查最终发布 Evidence，不运行全量测试。
2. Java、Rust、Go、Python、Node.js 语言/构建工具，local/development/test/staging/production 环境以及 application、container-kubernetes、wechat-miniprogram、github-skill 发布面从已批准 kit 闭集组合。
3. 发布顺序固定为最终 Evidence 检查、计划、可信宿主人类 plan approval、版本化脚本生成、可信宿主人类 execution approval、执行、发布后回读；旧脚本只能按确切版本与 digest 经人类确认后复用。
4. production 发布必须绑定备份、restore proof、rollback、benchmark 基线与发布后业务复核。数据库删除库、删除表、删除数据、truncate、cascade、reset/clean 以及无法静态闭合的间接脚本永远 fail closed，建议由人类在独立受控通道手动完成。
5. Evidence 最小分母固定包含 unit、API、E2E、Review、Completion Audit、artifact、package、SBOM、provenance 与 signature；调用方只能增加，不能减少。Evidence 必须为 typed、带 issuer、时间、候选绑定与可执行断言的当前文件。
6. plan/execution approval 必须由仓库外 trusted host 以 Ed25519、一次性 challenge、最小权限与数据库安全 attestation 签名；普通 JSON、argv、环境变量、路径或 approver 字符串不是批准能力。
7. receipt 统一复用 `scripts/v23/v236_security.py` 的 secret redaction；Cookie、数据库 URI、`.netrc`、云凭证与协作工具 token 不得进入持久化或公开产物。

## V2.44 测试能力与 V2.43 指标兼容

1. `references/testing-capability-manifest.json`、`references/testing-capability-protocol.md`、`schemas/v2.44/`、V2.44 benchmark、fixtures 与评分器继续作为历史机器合同；产品版本升级不改写其 schema 身份或固定 100 分分母。
2. V2.45 继续使用 `goal-teams-engineering-metrics-v2.43` sidecar；`pending`、`unavailable`、`not_applicable`、`insufficient_sample` 不得写成零。
3. 测试与指标均不能替代 SPEC、Harness、Evidence、Review、受信宿主验收或 Completion Audit。

## 发行与完成边界

1. V2.40 的 CP00–CP18 状态机、受保护 Git tree snapshot、route receipt、宿主 attestation、Cache Evidence 与公开扫描规则继续适用，V2.45 不得弱化其 fail-closed 语义。
2. V2.45 active 发行身份由 `scripts/release/release_config.py` 与 `references/release-profiles/v2.45.json` 的已提交 blob 冻结；V2.44 保留 predecessor 与宿主验签语义但 external write 必须拒绝。
3. V2.45 snapshot 继续使用 sealed source commit、唯一 generated OKF、严格四列 `_files.sha256` 与固定四公开资产；未知版本、两列清单或未独立批准的 public scan baseline 一律失败。
4. 固定 52 条自发布断言、iteration 9 隔离候选、iteration 11 delivery gate、四维评分与独立审计继续保留；评分、cache 与工程指标不能覆盖测试、Evidence、Review 或 Audit 失败。
5. CP05 对所有冻结了 `host_acceptance` 的版本都是 repository-external trusted-host transaction；public `promote/recover` 和 candidate 内 helper 必须零写拒绝，不得回落到调用方自报 Reviewer。
6. CP18 公开归档仅接收 `docs/archive/releases/V2.45/` 下经 sanitizer 处理的 completed/public 文件，不得包含 invocation、transport handle、绝对路径、raw log、secret 或 private provenance。

## 兼容边界

Portable Core 可由不同 Agent runtime 采用；缺少 command execution、vcs snapshot、独立成员、真实行为环境、可信人类确认或 host identity attestation 时，必须保持 `blocked|not_run|unavailable`，不能写 `accepted`、`achieved` 或计入满分。
