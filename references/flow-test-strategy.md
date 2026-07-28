---
type: Goal Teams Flow Test Strategy
title: Goal Teams V2.47 流程测试与 P0 冒烟策略
description: 为 small、medium、large 流程和 Goal Teams 产品面定义增量、P0 冒烟与最终全量回归的正交合同。
tags: [goal-teams, v2.47, testing, smoke, regression]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.47 流程测试与 P0 冒烟策略

## 权威来源

- 机器 SSOT：`references/flow-test-strategy-manifest.json`
- Schema：`schemas/v2.47/flow-test-strategy.schema.json`
- Validator：`scripts/checks/validate-v247-flow-test-strategy.py`

本协议不改写 V2.3、V2.44 或 V2.46 的历史 Evidence。测试集合和执行轮次是正交事实：
已有增量或冒烟通过记录不会因最终全量回归被删除，也不能抵扣最终全量回归的执行分母。

## 流程策略

| 流程 | 开发中 | 最终阶段 | 全量回归语义 |
| --- | --- | --- | --- |
| `small` | 必须运行受影响面的增量测试和 P0 冒烟 | 再次确认两类当前结果 | `not_required`；不得擅自扩大为全量 |
| `medium` | 必须运行受影响面的增量测试和 P0 冒烟 | 必须向用户澄清是否运行全量回归 | 未确认时 `awaiting_user_choice/blocked`；明确拒绝后按 small 收尾，确认后建立独立全量 run |
| `large` | 必须先运行受影响面的增量测试和 P0 冒烟 | 必须运行最终全量回归 | 从完整回归分母重新执行；不得引用前序结果作为本次 passed |

### 中型流程澄清门

中型流程在最终阶段只允许：

- 用户确认：创建新的 full-regression Check/Run/Evidence。
- 用户拒绝：记录 `not_required` 和用户决定。
- 未答复：保持 `awaiting_user_choice`，最终收尾 blocked；不得静默跳过澄清。

### 大型流程重新执行门

`large.final_full_regression.reuse_prior_results=false`。最终全量 run 必须有新的
`run_id`、`attempt_id` 和 Evidence；其分母等于版本冻结时的完整回归目录。增量和 P0
结果保留为历史与诊断证据，但不会把相同 case 从最终分母中删除。

## P0 用例合同

每条 P0 用例必须有：

- `input`：可复现的输入、状态或 fixture。
- `processing`：受控命令、编译、路由或状态转换。
- `expected_output`：用户或下游可观察结果。
- `assertions`：至少一个非退出码业务断言。

机器 manifest 同时登记：

1. 三种流程的 P0 用例；
2. manifest `product_surface_denominator` 中全部产品面的 P0 用例。

用例只证明登记产品面的关键路径可用，不替代完整功能、真实 API/E2E、发布或宿主验收。

## 影响分析

- 新增 V2.47 流程策略和 P0 用例是 `new_requirement`，初始为 `not_run`。
- 既有 V2.46 验证治理历史为 `unaffected`，保持原 Evidence identity。
- 与流程 gate、prompt 组装、runtime 选择和响应渲染直接相连的当前检查为 `affected`，需运行本轮增量/P0。
- 未运行全量回归不是 `invalid`；small 为 `not_required`，medium 未选择为 `awaiting_user_choice/blocked`，用户明确拒绝后按增量 + P0 收尾。
