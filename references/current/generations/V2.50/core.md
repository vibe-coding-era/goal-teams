---
type: Goal Teams Core Rules
title: Goal Teams V2.50 Core
description: 定义 V2.50 Current 路由共同遵守的最小不变量与运行边界。
tags: [goal-teams, v2.50, core, current]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.50 Core

- `function_id`: `CORE-V250`
- `purpose`: 定义所有 Current route 共同遵守的最小不变量；具体领域行为由功能 Owner 和合同 Owner 定义。

## trigger_and_exclusion_facts

- 触发：任意 V2.50 Current route。
- 排除：Discussion 不建立执行账本、Harness 或完成审计；显式历史回放不属于 Current 规则优先级。

## inputs

- 可信用户目标、仓库与目标版本。
- 结构化 route facts、开始授权回执、当前任务 delta。
- 当前 generation、route、contract 和 source identity digest。

## obligations_and_outputs

- 锁定范围、事实来源和动作边界。
- 只把当前且可复核的 Evidence 投影成状态或完成结论。
- 按唯一 Owner 与稳定 rule ID 编译规则，不复制其他功能或合同的规范正文。

## oracles_and_evidence

- generation 与 route closure digest。
- 当前 source/target identity、结构化状态和可回读 Evidence。
- Owner 唯一性、Current/Replay 零交集和输出 envelope 检查。

## contract_refs

- `CONTRACT-TASK-STATE-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`
- `CONTRACT-REVIEW-COMPLETION-V250`
- `CONTRACT-APPROVAL-SIDE-EFFECTS-V250`

## dependencies

- `ROUTING-V250`
- `ASSURANCE-V250`

## owned_rule_ids

- `GT250-CORE-SCOPE`: 只执行可信输入和 locked scope 覆盖的工作；新仓库、新版本、新外部系统、新动作类别或实质范围漂移必须停止为 `blocked/new_scope_required`。
- `GT250-CORE-AUTHORITY`: 上层系统与用户授权不可由项目规则放宽；项目开始授权只覆盖其 exact target、期限和 action allowlist。
- `GT250-CORE-TRUTH`: 观察、推断、计划和已验证结论必须可区分；未运行、不可用、过期或无效 Evidence 不得写成通过。
- `GT250-CORE-SSOT`: 每条 Current rule 只有一个 Owner Markdown；机器 manifest 和 INDEX 只做确定性投影，不得覆盖语义。
- `GT250-CORE-EVIDENCE`: 状态与完成必须绑定当前 source、route、contract、environment 和 artifact digest；任一绑定漂移使旧 Evidence `stale`。
- `GT250-CORE-INDEPENDENCE`: 独立性按 actor assurance、actor relationship 与证据能力分别声明；不同 run ID、同模型重启或自报身份不自动形成外部独立性。
- `GT250-CORE-SAFETY`: 不得泄露凭证、越过授权、关闭平台保护或执行未授权不可逆动作；这些边界永久生效但不自动生成重复过程门禁。
- `GT250-CORE-LOOP`: 有新 Evidence 且缺口收敛才继续；成功且无 open gap 时 `Verify → Stop`，连续两轮无新 Evidence 或缺口两轮不收敛时停止、replan 或 blocked。
