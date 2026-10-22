---
type: Goal Teams TaskList
title: 购物车折扣计算修复
generated_by: gt
---

# TaskList — 购物车折扣计算修复

- 目标状态：已结束（achieved）
- 模式：tracked · 风险：normal · 轮次：第 2 轮 / 预计 2 轮 · 计划：r1（已校验）
- 完成标准（Done Criteria）：
- 冻结任务图：4 个任务 · 总工作单元 128 · 加权关键路径 96
  - T1 剩余预算：{'work_units': 32, 'attempts': 16, 'revalidations': 16}
  - T1.1 剩余预算：{'work_units': 32, 'attempts': 16, 'revalidations': 16}
  - T1.2 剩余预算：{'work_units': 29, 'attempts': 15, 'revalidations': 14}
  - T2 剩余预算：{'work_units': 32, 'attempts': 16, 'revalidations': 16}
  C1. total() 按百分比折扣计算，并拒绝 0–100 之外的折扣（--check）
  C2. README 写明折扣参数

## 任务

| ID | 任务 | 父任务 | 负责 | 验证 | 依赖 | 状态 | 验收标准 | 证据 | 评审 |
|---|---|---|---|---|---|---|---|---|---|
| T1 | 折扣计算修复 |  | goal_backend | goal_reviewer |  | 已验收 | 子任务全部验收 |  | goal_reviewer pass |
| T1.1 | 补折扣边界测试 | T1 | goal_unit_test_designer | goal_reviewer |  | 已验收 | 覆盖百分比折扣与越界折扣 |  | goal_reviewer pass |
| T1.2 | 修复折扣实现 | T1 | goal_backend | goal_reviewer | T1.1 | 已验收 | total([100,50],10)==135；120 抛 ValueError | R8, R13, R24 | goal_reviewer pass |
| T2 | 更新 README 折扣说明 |  | goal_docs | goal_reviewer | T1.2 | 已验收 | README 写明折扣参数与取值范围 |  | goal_reviewer pass |

## 计划

- 分层（同层可并行）：L1: T1.1 · L2: T1.2 · L3: T1, T2
- 关键路径：T1.1 → T1.2 → T1（3）· 最大并行宽度：2
