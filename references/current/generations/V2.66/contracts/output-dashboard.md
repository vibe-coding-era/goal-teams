---
type: Goal Teams Functional Contract
title: Output Dashboard Contract
description: 定义 V2.66 六字段 Envelope 的结果内紧凑任务看板、Context 与 P/D/C/A LOOP 投影。
tags: [goal-teams, v2.66, output, dashboard, loop]
timestamp: 2026-08-26T00:00:00+08:00
okf_version: "0.1"
---

# Output Dashboard Contract

- `contract_id`: `CONTRACT-OUTPUT-DASHBOARD-V266`
- `purpose`: 在不改变外层六字段 Envelope 的前提下，用高信息密度、可验证的结果子视图展示执行状态。

## trigger_and_exclusion_facts

- 触发：任意非 Discussion、非 `plan_preview` 的用户可见执行更新。
- 排除：Discussion、preview、示例或缺失 current bindings 时不得生成非零完成数、Evidence、并行或成功状态。

## obligations_and_outputs

- `◆ Goal-Teams 任务执行看板` 显示任务/子任务完成汇总、真实 TaskList/状态机链接和 active/remaining 行；完成明细只进入完整 TaskList。
- 表格固定为 `优先级 | 任务 / 子任务 | Subagent 成员 | 进度`；父子关系是展示投影，`（并行）` 只来自 DAG `ready_layers`/派发事实。
- `◆ Context / Knowledge / Tools` 固定为 `核心规则 | 项目知识 | 代码库 | MCP/CLI/API`；每项为真实链接，项目知识必须包含 `memory.md`，代码库只显示工程名。
- `◆ LOOP：第 <当前轮> 轮 / 预计 <总轮> 轮` 固定使用 P/D/C/A 四行；P 标签为 `P ｜ 计划 / 下一轮目标`，C 链接 `Banchmark.md`，A 链接 `loop-review.md`。
- 结构化输入与 Markdown 输出由 `schemas/v2.66/output-dashboard.schema.json` 和 `scripts/v266/output_dashboard.py` 约束。
- `renderer-first`：Goal Lead 必须从 current TaskList、状态机、Evidence、Banchmark、loop-review 与实际 Context 先构建 dashboard view，调用 `validate_dashboard` 后调用 `serialize_dashboard`，并把返回 Markdown 原样作为 `结果` 子视图。禁止手写 Dashboard/Context/LOOP、沿用旧六字段摘要或以叙述替代 renderer；view 缺失或校验失败时必须 fail-closed 为 `blocked|replan`。

## oracles_and_evidence

- TaskList、状态机、Evidence、Banchmark、loop-review digest 与 freshness bindings；执行态逐项核对状态机中的计数、active rows、`ready_layers`、LOOP，以及 Evidence 文件中的新增数量。
- 结构化输入使用仓库相对路径并拒绝越界、缺失、目录和符号链接；用户可见 Markdown 将已验证的本地路径投影为绝对链接。MCP/CLI/API 当前只接受仓库内实际引入的上下文产物，外部 URL 不在本合同的 readback 保证内。
- schema validation、deterministic render、真实链接 readback 与外层六字段 Envelope validation。

## dependencies

- `CONTRACT-TASK-STATE-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`

## owned_rule_ids

- `GT266-OUTPUT-ORDER`: 结果子视图严格按 Dashboard → Context → LOOP 排序，不增加外层字段。
- `GT266-OUTPUT-TRUTH`: 计数、父子展示、并行、链接、Evidence、缺口、阻塞和决策必须绑定 current receipts；preview/example fail closed。
- `GT266-OUTPUT-CONTEXT`: Context 非空项必须是真实链接，项目知识包含 `memory.md`，代码库只显示工程名。
- `GT266-OUTPUT-PDCA`: LOOP 标题含当前/预计轮次，P/D/C/A 四行分别承载计划、执行、检查和调整。
- `GT266-OUTPUT-RENDERER-FIRST`: 执行型结果只接受经 renderer 的 current view；不能生成或验证 view 时不输出手写替代看板。
