---
type: Release Protocol
title: Goal Teams Skill 简单发行规范
description: 适用于纯 Skill 仓库的五步本地验证、一次人工发布确认与发布后验真。
tags: [goal-teams, skill, release, simple]
timestamp: 2026-07-30T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Skill 简单发行规范

## 适用范围

本仓库交付物是 Skill 包，不是需要数据库迁移、服务灰度、容器编排或基础设施回滚的业务程序。
默认使用 `skill_simple`，不建立 CP00–CP18 状态机，不要求两阶段签名批准、nonce authority、
独立 review authority 或仓库外 trusted-host。

只有发行内容实际包含凭证处理、支付/认证、数据库或服务变更、破坏性基础设施操作、自动外部写入，
或者用户明确要求高保障发行时，才升级到
`references/release-packaging-protocol.md` 的 `governed_release`。

## 五步发行

| Gate | 内容 | 通过条件 |
| --- | --- | --- |
| S0 Freeze | 冻结 `VERSION`、source commit/tree、tag 与 package manifest | 版本投影一致；工作树与候选身份明确 |
| S1 Check | 运行 `./scripts/check.sh` 和本次变更的定向测试 | 必需检查通过；skip/blocked 单独列出，不计 passed |
| S2 Package | 从冻结 commit 按 allowlist 构建两次并校验 safe tar、hash、secret/public surface | 两次产物逐字节一致；仅包含 Skill 交付物 |
| S3 Install rehearsal | 在隔离目录验证 install、update、失败回滚、uninstall 与 installed tree identity | 不写正式 Codex home；生命周期全部通过 |
| S4 Publish | 用户确认后执行 tag、GitHub Release；再下载资产并复核 hash/安装 | 外部写前有一次明确确认；tag 不覆盖；回下载验真通过 |

S0–S3 是本地验证，不需要用户先批准“发行计划”。S4 的一次人工确认必须绑定：

- version、source commit/tree 与 tag；
- 固定资产名和 SHA-256；
- 将执行的外部操作：push/tag/GitHub Release；
- 是否执行正式安装。

确认只授权列出的操作；没有确认时只输出 `ready_for_publish_approval`，不得写 GitHub、
tag、正式安装目录或 Release。

## 单一发行凭证

简单发行只维护一份 `skill-release-receipt.json`，包含：

- source version/commit/tree；
- S1 命令及结果；
- 两次构建的资产 hash；
- S3 隔离安装生命周期结果；
- Reviewer 结论；
- S4 用户确认文本与时间（尚未确认时为 `null`）；
- GitHub/tag/download/install 回读（尚未执行时为 `not_run`）。

不为普通 Skill 发行建立完整 Goal Teams ledger、九任务图、CP checkpoint、签名批准文档或
nonce 消费状态。测试、报告和历史失败可以保留在 `docs/`，但不得进入发行包。

## 最小独立检查

- `docs_only`：结构/链接检查，加一名独立 Reviewer；通常随下一次 Skill 版本一起发布。
- `skill_bundle`：S0–S4 全部适用；脚本、schema、installer 变化增加对应定向测试。
- `governed_release`：仅在命中高风险升级条件时使用历史高保障协议。

V2.48 `skill_bundle` 的 GitHub 必需状态检查只包含 `check-macos` 与
`release-asset-gate`。`check-ubuntu` 属于历史 governed/cross-platform 深度验证面，
不得成为 small 流程或普通 Skill 发行的合并门禁。常规 Ubuntu 回归可以保留为非阻断检查；
若实际变更命中跨平台执行风险，再按影响分析升级定向测试或 `governed_release`。

规则变化不会使历史测试自动 `invalid`。旧结果保留为 historical；受影响用例标
`stale/retest_required`，新简单发行门禁按当前候选重新执行。

## 失败语义

- 本地命令失败：`failed`。
- 当前平台不能建立测试前置条件：`blocked`，不计 passed。
- 候选未冻结：S2/S3 的实际候选验证为 `not_run`。
- 未取得 S4 人工确认：发布状态为 `ready_for_publish_approval`，不是 failed。
- GitHub/tag/正式安装未获授权：`not_authorized`。
