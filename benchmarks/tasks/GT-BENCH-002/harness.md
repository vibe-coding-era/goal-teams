# GT-BENCH-002 Harness

本 harness 是人工执行说明，不是自动 runner。评测者用它保持 `baseline` 和 `goal-teams` 两种模式输入一致，并收集可复盘证据。

## 运行前准备

1. 记录仓库路径、分支、基准提交和 `git status --short`。
2. 确认执行模式：`baseline` 或 `goal-teams`。
3. 将 [`task.md`](task.md) 的“统一输入提示”复制给执行者，只替换 `<mode>`。
4. 确认输出目录为 `outputs/GT-BENCH-002/<mode>/`。
5. 若运行仓库校验，优先使用既有 `./scripts/check.sh`；本 benchmark 不要求新增校验脚本。

建议记录格式：

```text
Benchmark ID: GT-BENCH-002
Mode: baseline | goal-teams
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

1. 单个执行者读取统一输入和必要源文件。
2. 直接创建生产流门禁包。
3. 自查文件结构、JSON/YAML 可读性和最终门禁结论。
4. 保存最终回复、diff、校验输出摘要和耗时/资源字段。

Baseline 不应伪装成多成员协作，也不应声称完成独立校验，除非有实际可引用的独立评审记录。

## Goal Teams 执行

Goal Lead 应至少拆出以下职责，成员数量可按环境调整：

| 职责 | 典型 Skill/Subagent | 锁定范围 | 输出 |
| --- | --- | --- | --- |
| 发布门禁文档 | `goal_docs` 或产品/文档成员 | `outputs/GT-BENCH-002/goal-teams/` | release gate、pipeline gates、safety boundaries |
| 证据账本 | `goal_qa` 或文档成员 | `outputs/GT-BENCH-002/goal-teams/` | evidence ledger、缺口表 |
| 安全边界评审 | `goal_reviewer` | read-only | 禁止行为和停止条件评审 |
| 收尾审计 | `goal_completion_auditor` | read-only | 未完成工作、自动续跑和阻塞判断 |

Goal Teams 模式应保留：

- `Teams 规划表` 或等价分工记录。
- 每个成员的 locked scope、owner、交付物和验证责任。
- 只读评审或收尾审计证据。
- 若发现可自动续跑事项，记录续跑任务；若发现安全边界或外部审批，记录阻塞。

## 证据采集

每次运行至少保留：

- 输出目录文件列表。
- `git diff -- outputs/GT-BENCH-002/<mode>/` 或等价 diff。
- `release-gate.md` 中的最终门禁结论。
- `evidence-ledger.json` 中缺口项数量和状态。
- `pipeline-gates.yaml` 中每个 gate 的 decision。
- `auto-continue-plan.md` 中自动续跑项和停止项。
- `safety-boundaries.md` 中禁止行为清单。
- 校验命令和结果摘要。
- 最终中文回复。

可选保留：

- 运行过程中的中间状态。
- 失败尝试和修正记录。
- tokens、费用、工具调用次数。

## 模式对照表

评分前建议填写：

| 指标 | baseline | goal-teams | 证据 |
| --- | --- | --- | --- |
| 门禁结论 |  |  | `release-gate.md` |
| 未闭合证据缺口数 |  |  | `evidence-ledger.json` |
| 自动续跑项数 |  |  | `auto-continue-plan.md` |
| 停止条件数 |  |  | `safety-boundaries.md` |
| 独立校验证据 |  |  | 最终回复或成员记录 |
| 耗时 / tokens / 费用 |  |  | run notes |

## 停止条件

- 执行者需要真实生产、凭证、支付、认证、外部审批或 CI 写入才能继续。
- 执行者要修改禁止范围才能完成任务。
- 执行者无法创建输出目录或无法读取必要示例文件。
- 仓库并发改动导致校验失败，且无法确认与本 benchmark 输出无关。

遇到停止条件时，应记录已完成产物和阻塞原因，不扩大范围修复。
