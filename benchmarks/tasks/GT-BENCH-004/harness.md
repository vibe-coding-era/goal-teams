# GT-BENCH-004 Harness

本 harness 是人工执行说明，不是自动 runner。评测者用它保持 `baseline`、`goal-teams-v2.02` 和 `goal-teams-v2.1-loop` 三种模式输入一致，并收集可复盘证据。本文不声明存在真实自动续跑 runner；“自动续跑”只指 Lead 在已确认范围内可以继续安排的下一轮工作。

## 运行前准备

1. 记录仓库路径、分支、基准提交和 `git status --short`。
2. 确认执行模式：`baseline`、`goal-teams-v2.02` 或 `goal-teams-v2.1-loop`。
3. 将 [`task.md`](task.md) 的“统一输入提示”复制给执行者，只替换 `<mode>`。
4. 确认输出目录为 `outputs/GT-BENCH-004/<mode>/`。
5. 若运行仓库校验，优先使用既有 `./scripts/check.sh`；本 benchmark 不要求新增校验脚本或 runner。

建议记录格式：

```text
Benchmark ID: GT-BENCH-004
Mode: baseline | goal-teams-v2.02 | goal-teams-v2.1-loop
Repo: `<repo-root>`
Base commit: <commit>
Branch/worktree: <branch or path>
Started at: <ISO-8601>
Ended at: <ISO-8601>
Model/tooling: <name if available>
User/tokens/cost: 用户：<name or 未提供>；tokens：<value or 未提供>；费用：<value or 未提供>
Pre-existing changes: <summary>
```

## Baseline 执行

1. 单个执行者读取统一输入和必要示例文件。
2. 直接创建 LOOP 状态包。
3. 自查文件结构、JSON 可读性、证据缺口和最终 Loop Decision。
4. 保存最终回复、diff、校验输出摘要和资源字段。

Baseline 不应伪装成 Goal Teams，也不应声称有独立成员、收尾审计或 LOOP runner，除非运行记录中有实际可引用证据。

## Goal Teams V2.02 执行

1. Goal Lead 按 V2.02 规则拆出文档、QA 或 Reviewer 职责。
2. 成员可以记录自动续跑和缺证打回，但不强制使用 V2.1 LOOP 状态字段。
3. 必须保留成员分工、locked scope、只读校验或收尾审计证据。
4. 若产物缺少可恢复 `loop-state.json` 或明确 Loop Gate，应在评分中如实记录。

该模式用于观察 V2.02 在缺证续跑场景下的自然表现，不要求执行者伪装成 V2.1。

## Goal Teams V2.1 LOOP 执行

Goal Lead 应至少覆盖以下职责，成员数量可按环境调整：

| 职责 | 典型 Skill/Subagent | 锁定范围 | 输出 |
| --- | --- | --- | --- |
| LOOP 决策记录 | Goal Lead 或 `goal_docs` | `outputs/GT-BENCH-004/goal-teams-v2.1-loop/` | `lead-loop-decision.md`、`progress.md` |
| 状态快照 | Goal Lead 或 QA 成员 | 同输出目录 | `loop-state.json` |
| 证据缺口账本 | `goal_qa` | 同输出目录 | `evidence-gaps.md` |
| 停止边界评审 | `goal_reviewer` | read-only | `stop-boundaries.md` 评审结论 |
| 收尾审计 | `goal_completion_auditor` | read-only | 自动续跑、阻塞和恢复性结论 |

V2.1 LOOP 模式应保留：

- `Teams 规划表` 或等价分工记录。
- Loop Decision 和 Loop Gate 的中途判断。
- progress / loop-state 状态快照。
- 可自动续跑项和必须停止项的分离证据。
- 独立 QA、Reviewer 或 completion audit 对证据闭环的检查。

## 证据采集

每次运行至少保留：

- 输出目录文件列表。
- `git diff -- outputs/GT-BENCH-004/<mode>/` 或等价 diff。
- `lead-loop-decision.md` 中的当前 Loop Decision。
- `loop-state.json` 中的 `decision`、`gates`、`evidence_gaps`、`auto_continue_items`、`stop_boundaries`。
- `progress.md` 中观察和结论的区分。
- `auto-continue-plan.md` 中可自动续跑项。
- `stop-boundaries.md` 中必须用户确认或外部审批的事项。
- `evidence-gaps.md` 中缺失证据及补齐路径。
- 校验命令和结果摘要。
- 最终中文回复和资源消耗字段。

可选保留：

- 中间状态快照或循环次数记录。
- 失败尝试和修正记录。
- tokens、费用、工具调用次数。
- 独立校验者或 completion auditor 的只读结论。

## 模式对照表

评分前建议填写：

| 指标 | baseline | goal-teams-v2.02 | goal-teams-v2.1-loop | 证据 |
| --- | --- | --- | --- | --- |
| Loop Decision 是否明确 |  |  |  | `lead-loop-decision.md` |
| Loop Gate 是否覆盖范围/证据/安全/成本/完成 |  |  |  | `lead-loop-decision.md`、`loop-state.json` |
| 是否误判完成 |  |  |  | 最终回复、`progress.md` |
| 自动续跑项是否限于已确认范围 |  |  |  | `auto-continue-plan.md` |
| 停止边界是否具体 |  |  |  | `stop-boundaries.md` |
| 证据缺口是否可追溯 |  |  |  | `evidence-gaps.md` |
| 状态是否可恢复 |  |  |  | `loop-state.json` |
| 独立校验证据 |  |  |  | 成员记录或最终回复 |
| 耗时 / tokens / 费用 |  |  |  | run notes |

## 停止条件

- 执行者需要修改禁止范围才能完成任务。
- 执行者需要真实生产、凭证、支付、认证、安全敏感系统、外部审批或 CI 写入才能继续。
- 执行者试图把缺失证据写成已完成，且无法在本轮修正。
- 仓库并发改动导致校验失败，且无法确认与本 benchmark 输出无关。
- 缺少权限导致无法创建 `outputs/GT-BENCH-004/<mode>/`。

遇到停止条件时，应记录已完成产物、Loop Decision、停止原因和恢复所需输入，不扩大范围修复。
