---
type: Goal Teams Core Policy
title: Goal Teams Core V2.5
description: Goal Teams V2.36 保留的通用协作、证据与完成策略。
tags: [goal-teams, core, v2.5, policy-profile, okf]
timestamp: 2026-07-12T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Core V2.5

机器名：`goal-teams-core-v2.5`。

这是 V2.36 对所有普通项目默认启用的通用核心。它只定义可跨项目复用的目标、账本、验证、安全和完成语义，不包含 Goal Teams 仓库自身的固定断言数量、固定迭代编号、评分表或公开归档布局。

## 通用能力

1. 将目标约束为 Done Criteria、Requirement/AC、任务依赖与 locked scope。
2. append-only ledger 是执行事实源，`TaskList.md` 只由 reducer 投影。
3. 使用 `SPEC -> Harness -> Evidence -> Review -> Completion Audit` 建立可追踪验证链。
4. required 交接物绑定 Owner、Validator、run identity、当前 Evidence 和独立检查；作者不能自我批准。
5. 新范围、破坏性动作、凭证、外部写入、安全敏感变更和 Budget 超限停在授权门前。
6. 长任务按 `Gather -> Reason -> Act -> Verify -> Repeat` 续跑；轮次上限、停止条件和恢复文件由当前项目计划决定，不使用固定第 9/11 轮。

## 执行等级

| 等级 | 典型范围 | 最小门禁 |
| --- | --- | --- |
| `lite` | small、low risk、非发布、无安全覆盖的局部文档/配置/CLI/原创 UI 小改 | scoped contract、目标检查、当前 Evidence；Architecture/完整环境报告/独立测试按影响触发 |
| `standard` | medium，或 small 但涉及 backend/API、medium risk、跨文件行为 | 影响分析、当前环境预检、适用独立测试、Evidence、独立 Review；Architecture 按合同/API/数据边界触发 |
| `full` | large、release、reference-driven UI/复刻、多系统或广泛回归 | Architecture、Environment、独立测试、Harness/Evidence、适用全回归和独立 Completion Audit 全部强门 |
| `regulated` | high/critical risk、安全、认证、支付、迁移、破坏性动作或高风险外部写入 | `full` 全部门禁，加 safety review、授权与安全 Evidence；不得由规模降级 |

执行等级只改变适用门禁的数量和深度，不改变未验证不得宣称成功、Evidence 当前性、授权边界或作者不得自我批准。

## 自动派生

- `policy_profile`、`state_gate_profile`、`task_type`、执行等级与 `gate_profile`（派生 gates 集）必须由可信 adapter 根据产品版本、已验证目标仓库、任务事实、规模和风险生成。
- `state_gate_profile` 省略时仍由 runtime 自动派生并执行；显式提供时必须与派生值完全一致，否则 fail closed。调用方不能借字段存在或缺失自选门禁。
- 只有 `goal-teams` 仓库的当前 V2.39 自发布任务才派生 `goal-teams-self-release-v2.39`；其他任务保持本 Profile，历史 V2.36/V2.37/V2.38 数据仍按兼容契约只读 replay。
- 原创 UI 使用真实浏览器/DOM/几何/截图 Evidence，不因 `ui=true` 自动升级 `full`，也不加载 reference-driven pixel baseline 协议。
- 复刻、临摹或参考驱动 UI 派生 `ui_replica`，至少为 `full` 并加载像素基线协议。

## V2.36 信任链

- 所有日志、Evidence、memory 和公开副本统一使用 `scripts/v23/v236_security.py`；Authorization/Cookie、云凭证、协作工具 token、private key、JWT 与敏感 URL 都先检测并脱敏。
- acceptance 源码快照使用 `v236-snapshot-create <repo> --baseline <commit> --receipt <private-path>`；runtime 自动纳入全部 tracked 修改/删除与 non-ignored untracked，不接受调用方 `source_paths`。临时 Git index/object DB 只读引用主 objects，主 HEAD/refs/index/object store 前后必须一致；用 `v236-snapshot-validate` 重建验证。
- V2.36 独立身份 registry 的每个 identity 都包含宿主 HMAC-SHA256 attestation，绑定 issuer、run、transport、nonce、签发/过期时间和 identity core hash。纯验证接口仅用于诊断；acceptance 必须使用宿主私有 challenge state 跨调用拒绝重放，trust key 只存在于仓库外宿主进程，不得进入 Agent 环境、argv、registry、Evidence 或日志。
- 候选仓库 runtime 对 V2.36 Completion 始终返回 `E_V236_HOST_ADAPTER_REQUIRED`，不接受 Python/CLI 注入 key/state/issuer/context。仓库外宿主在不可变输入副本上消费签名 route receipt、完整 protected snapshot 与 attested identity registry；route receipt 绑定实际仓库 fingerprint/kind 和 trusted release base，后者必须等于 snapshot `baseline_commit`。Audit、Review、Harness 使用同一个完整 `goal-teams-v2.36-acceptance-binding-v1`；每条 current Evidence 使用非循环的 `goal-teams-v2.36-acceptance-core-binding-v1` 绑定同一 product/route/target/snapshot/identity/base/profile。完整 binding 还覆盖 TaskList 与自动发现引用日志/报告/artifact 的 acceptance-input snapshot；省略任一输入不能降级到 legacy 完成链。
- route receipt 还必须签名宿主重派生的 execution profile、required review class、完整 gates/conditional scopes 与 execution-contract digest。required gate 只能由真实 passed Check、current core-bound Evidence 和 accepted Task 闭合；conditional N/A 绑定 route scope 与 impact decision。`completion_audit` 是唯一 graph-external gate，禁止 Task/Check/Evidence 自引用，只由当前宿主 Audit verdict 与 binding hash 证明。

## 完成边界

通用完成只取决于当前范围的 required tasks/checks、追踪覆盖、适用测试、Review、安全门和独立 Completion Audit。固定 52 条断言、第 9/11 轮、四维评分与 `docs/archive/...` 不是通用完成条件。
