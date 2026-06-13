# GT-BENCH-001 Harness

本 harness 是人工执行说明，不是自动 runner。执行者可以按这里记录环境、输入、命令和产物，评分者据此复盘 baseline 与 Goal Teams 的差异。

## 运行前准备

1. 记录仓库路径、当前分支和基准提交。
2. 记录 `git status --short`，保留已有未跟踪或未提交改动的说明。
3. 确认执行模式：`baseline` 或 `goal-teams`。
4. 使用 [`task.md`](task.md) 的“统一输入提示”，不额外加入隐藏要求。
5. 如需运行校验，优先使用仓库既有 `./scripts/check.sh`。

建议记录格式：

```text
Benchmark ID: GT-BENCH-001
Mode: baseline | goal-teams
Repo: /Users/Rou/dev_projects/goal-teams
Base commit: <commit>
Branch/worktree: <branch or path>
Started at: <ISO-8601>
Ended at: <ISO-8601>
Model/tooling: <name if available>
User/tokens/cost: 用户：<name or 未提供>；tokens：<value or 未提供>；费用：<value or 未提供>
Pre-existing changes: <summary>
```

## Baseline 执行

1. 单个执行者读取必要项目指南和任务输入。
2. 直接在允许范围内完成文档模板。
3. 运行可用校验，或说明未运行原因。
4. 保存最终回复、diff 和校验输出摘要。

Baseline 不应模拟多个成员，也不应额外创建 Goal Teams 运行时文件。

## Goal Teams 执行

1. Goal Lead 将任务拆成至少两个职责：文档产出与只读校验。
2. 每个成员必须有明确 `member_id`、`skill_or_subagent`、`locked_scope`、交付物和输出契约。
3. 文档成员只修改 `benchmarks/`。
4. 校验成员只读检查范围、结构、评分可操作性和 README/validate 同步建议。
5. Lead 汇总 diff、校验证据、剩余风险和资源消耗。

Goal Teams 模式只有在产物质量、独立校验、风险控制或复盘性上体现证据，才应被判定优于 baseline。

## 证据采集

每次运行至少保留：

- 最终文件列表。
- `git diff -- benchmarks/` 或等价 diff。
- 校验命令和结果摘要。
- 最终中文回复。
- 若是 Goal Teams 模式，保留成员分工、校验者结论和 Lead 整合说明。

可选保留：

- 开始和结束时间。
- 中间状态记录。
- 失败尝试和修正记录。
- tokens、费用、工具调用次数。

## 停止条件

- 执行者需要修改禁止范围才能继续。
- 仓库校验因其他成员并发改动失败，且无法确认与本 benchmark 任务无关。
- 缺少必要权限或工具导致无法写入 `benchmarks/`。
- 任务输入被变更，导致无法和其他运行横向比较。

遇到停止条件时，记录阻塞原因并提交已完成的证据，不要扩大范围修复。
