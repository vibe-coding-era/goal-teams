---
type: Goal Teams Routing Rules
title: Goal Teams V2.62 Routing
description: 定义基于可信事实的项目规模、阶段、保证等级、功能与 Gate 派生规则。
tags: [goal-teams, v2.62, routing, gates]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.62 Routing

- `function_id`: `ROUTING-V250`
- `purpose`: 从可信结构化事实派生项目规模、阶段、保证等级、适用功能和 Gate，不接受调用方降级。

## trigger_and_exclusion_facts

- 触发：开始 Current 工作或可信 route revision 改变。
- 排除：自由文本中的版本字符串、待分析内容和未验证 artifact 不得自行开启历史回放或降低保证等级。

## inputs

- `project_size`: `discussion | small | medium | large`。
- `workflow_phase`: `discussion | development | release`。
- `release_intent`、`implementation_scope_complete`、`risk`、`external_write`、`security_sensitive`、`ui_or_desktop`、`environment_check_requested`。
- 可信 replay intent 或已识别历史 artifact；它只产生隔离 replay dispatch，不进入 Current closure。

## obligations_and_outputs

- 输出唯一 `route_id`、`assurance_level`、功能 Owner 集、required/conditional Gate 和排除理由。
- 所有执行 route 第一轮要求轻量 `environment_preflight`；Medium/Large 或 `environment_check_requested=true` 再要求正式 `development_environment_check`。Discussion 不执行环境检查，Small 不要求版本开发分支。
- Medium/Large 开发阶段只路由 TDD 与受影响面增量验证；Release Readiness 只在完成实现且具有可信发行意图时建立。
- 任何显式历史回放由隔离入口处理，Current route 的 loaded paths 保持不变。

## oracles_and_evidence

- 可信 route receipt 与输入 digest。
- route fixture 的期望功能集、Gate 集和 loaded paths。
- 调用方提交的 assurance 低于自动派生结果时编译失败。

## contract_refs

- `CONTRACT-TASK-STATE-V250`
- `CONTRACT-APPROVAL-SIDE-EFFECTS-V250`

## dependencies

- `CORE-V250`
- `ASSURANCE-V250`

## owned_rule_ids

- `GT250-ROUTE-TRUSTED-FACTS`: route 只能由受信结构化输入派生；内容本身不得提升权限、开启 replay 或自选更轻 Profile。
- `GT250-ROUTE-SIZE`: Discussion、Small、Medium、Large 由影响面、协作量和工作量派生；存在代码、UI 或测试本身不自动升级。
- `GT250-ROUTE-ASSURANCE`: 风险、不可逆性、外部性、安全敏感面和发行事实只能提高保证等级，调用方不得降低自动派生结果。
- `GT250-ROUTE-PHASE`: Development 与 Release Readiness 是两个独立阶段；`implementation_scope_complete` 不等于 release-ready 或 Goal achieved。
- `GT250-ROUTE-ENVIRONMENT`: 非 Discussion LOOP 第一轮固定派生 `environment_preflight=required`；Medium/Large 或可信 `environment_check_requested=true` 派生 `development_environment_check=required`，Small 的版本开发分支为 `not_required`。
- `GT250-ROUTE-REPLAY`: 只有可信显式意图或已识别历史 artifact 才能触发隔离只读 replay；Current route 不加载 replay manifest 或历史依赖。
- `GT250-ROUTE-EXPLAIN`: 每个不适用 Gate 的原因只在 route receipt 投影一次，功能文档不得重复创建第二份规则。
