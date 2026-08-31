---
type: Goal Teams Core Rules
title: Goal Teams V2.67 Core
description: 定义 V2.67 Current 路由共同遵守的最小不变量与运行边界。
tags: [goal-teams, v2.67, core, current]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.67 Core

- `function_id`: `CORE-V250`
- `purpose`: 定义所有 Current route 共同遵守的最小不变量；具体领域行为由功能 Owner 和合同 Owner 定义。

## trigger_and_exclusion_facts

- 触发：任意 V2.67 Current route。
- 排除：Discussion 不建立执行账本、Harness 或完成审计；显式历史回放不属于 Current 规则优先级。

## inputs

- 可信用户目标、仓库与目标版本。
- 结构化 route facts、开始授权回执、当前任务 delta。
- 当前 generation、route、contract 和 source identity digest。

## obligations_and_outputs

- 锁定范围、事实来源和动作边界。
- 任意执行型 LOOP 的第一轮先建立 TaskList、分配任务并派发独立环境检查；Discussion 与显式 `plan_preview` 不落执行状态。
- 只接纳有当前消费者、可观察验收、预算和退出条件的工作；冻结后用 `TaskExactSet` 与 DAG 计算任务数、关键路径和最大并行宽度。
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
- `GT250-CORE-LOOP`: 有新 Evidence 且缺口收敛才继续；每轮用户可见进度反馈当前轮次/总轮次；成功且无 open gap 时 `Verify → Stop`，终局除 Benchmark 外给出基于 Evidence 的 LOOP 改进建议；连续两轮无新 Evidence 或缺口两轮不收敛时停止、replan 或 blocked。
- `GT250-CORE-FIRST-LOOP`: 任意非 Discussion、非 `plan_preview` LOOP 的第一轮必须先建立 `TaskList`、分配任务并派发独立 `goal_release_engineer` 的 `environment_preflight` 模式；这些首轮事实未闭合前不得进入实现。
- `GT263-CORE-PREDICTABLE-TIME`: 范围与预算形成工作量上界；exact-set/DAG 使任务数量、顺序、依赖与关键路径可计算；无消费者需求不进入当前开发，外部 blocker 不触发无关返工，finding 修复受验真、范围、消费者与预算限制，每项任务都有固定验证和退出条件。
- `GT263-CORE-PREDICTABLE-QUALITY`: 输入、代码、测试与结果绑定 digest、receipt 和 Git baseline；真实差异由 Git 自动采集，TDD、固定回归和独立审计形成分层验证，`BLOCKED` 可作为真实结论，工程、运行与业务完成保持正交。
