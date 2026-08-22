---
type: Goal Teams Function Rules
title: Agent Runtime Function
description: 定义 Agent 产品、上下文、工具、成员协作与运行时切换规则。
tags: [goal-teams, v2.65, agent-runtime, tools]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Agent Runtime Function

- `function_id`: `FUNCTION-AGENT-RUNTIME-V250`
- `purpose`: 拥有 Agent 产品、Prompt/Context、工具、成员派发、宿主能力和 generation transition 的运行时规则。

## trigger_and_exclusion_facts

- 触发：任务涉及 Agent 产品、Prompt、Context/Memory/Cache、MCP、Browser、Computer Use、Playwright、成员协作或 runtime transition。
- 排除：平台文档、候选 adapter 或自报能力不能当作真实宿主执行 Evidence。

## inputs

- runtime capability observation、成员角色需求、tool surface、generation/route/prompt digest 和 fresh-process receipt。

## obligations_and_outputs

- 只加载命中角色与工具所需的最小 Prompt/规则 closure。
- 派发记录稳定 member ID、run ID、locked scope、输入/输出合同和停止条件。
- 执行型 LOOP 第一轮必须派发与实现 Owner 不同 run 的 `goal_release_engineer`，并锁定为轻量 `environment_preflight` 模式；其结果由 Goal Lead 合并，环境成员不得实现业务变更或自批环境。
- 启动时只读取一次 ACTIVE 并冻结 `GenerationSnapshot`；后续轮次不得重新读取或热切换。selected root、ACTIVE 或 generation epoch 变化时当前会话返回 `E_ACTIVE_CHANGED_RESTART_REQUIRED`。
- route 只能从可信 `ProjectRouteFacts` 唯一派生；PromptArtifact 绑定实际编译字节。宿主观察与 Provider 最终 assembly 分开声明，缺少 Provider 证明时保持 `unavailable`。
- generation cutover 后必须由候选之外的 adapter 启动 fresh process 并重新读取 active generation；同进程自报切换无效。

## oracles_and_evidence

- runtime/tool discovery、实际调用回执、成员关系、Prompt plan digest 和 transition receipt。

## contract_refs

- `CONTRACT-TASK-STATE-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`
- `CONTRACT-REVIEW-COMPLETION-V250`

## dependencies

- `CORE-V250`
- `ROUTING-V250`

## owned_rule_ids

- `GT250-RUNTIME-CAPABILITY`: 每项 runtime/tool 能力必须区分 documented、discovered、executed 和 verified；未实测能力不得宣称可用。
- `GT250-RUNTIME-PROMPT`: Prompt plan 必须绑定 active generation、route、ordered refs、byte count 和 digest；未命中的功能不得加载。
- `GT250-RUNTIME-DISPATCH`: 成员派发绑定稳定身份、locked scope、合同、交付物和停止条件；首轮环境检查绑定独立 `goal_release_engineer/environment_preflight`，成员不得自行扩大范围或自证完成。
- `GT250-RUNTIME-ASSURANCE`: actor assurance 与 relationship 分轴记录；同模型、同控制器或相关成员复核不能标为外部独立。
- `GT250-RUNTIME-TRANSITION`: active generation 改变后必须建立 fresh-process transition receipt；任一 source、bootstrap、generation、prompt、route 或 checker digest 漂移使其 stale。
- `GT263-RUNTIME-DISCOVERY`: 每个宿主搜索域只允许一个 active `goal-teams`；候选 identity 不完全相同、多旧副本或无确定选择时 fail closed，不得回退到旧版本。
- `GT263-RUNTIME-SNAPSHOT`: 会话持有不可变 GenerationSnapshot；文件事件只能使其 invalid 并要求新会话，不能把新 ACTIVE 热加载进旧会话。
- `GT263-RUNTIME-FACT-ROUTE`: 调用方不得提交最终 route ID；DerivedRouteReceipt 必须绑定 facts digest、assurance floor、required/conditional gates 与排除理由。
- `GT263-RUNTIME-PROMPT-OBSERVATION`: `prompt_plan_sha256`、`compiled_prompt_sha256` 与 HostLoadObservationReceipt 分别表示计划、编译字节和宿主观察；仓库不得冒充 Provider 最终 assembly 证明。
