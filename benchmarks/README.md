# Goal Teams Benchmarks

本目录用于沉淀可复盘的 benchmark 任务，评估 Goal Teams 相比单会话或临时协作方式是否真的带来更好的结果。这里只提供轻量 task package 检查脚本，不声明真实自动执行 runner；每个 benchmark 主要定义输入、人工执行方法、评分标准和期望产物。

## 目标

- 用同一份任务输入比较 `baseline` 和 `goal-teams` 两种执行方式。
- 记录产物质量、范围遵守、独立校验、文档完整度、耗时、tokens 和费用。
- 让评分者可以仅凭任务文件、运行记录和最终 diff 复盘结论。
- 为后续版本判断 Goal Teams 规则是否改进提供稳定样本。

## 目录结构

```text
benchmarks/
  README.md
  tasks/
    GT-BENCH-001/
      task.md
      harness.md
      scoring.md
      expected-artifacts.md
    GT-BENCH-002/
      task.md
      harness.md
      scoring.md
      expected-artifacts.md
    GT-BENCH-003/
      task.md
      harness.md
      scoring.md
      expected-artifacts.md
```

新增 benchmark 时优先复制 `GT-BENCH-001` 的结构，并保持任务编号稳定。任务编号建议使用 `GT-BENCH-NNN`。

## 执行模式

- `baseline`：单个 Codex 会话按任务提示直接完成，不显式启动 Goal Teams。
- `goal-teams`：由 Goal Lead 拆分成员，成员按 locked scope 和独立校验要求完成。
- `review-only`：可选，只评分不执行，用于训练评分一致性。

两种执行方式必须使用同一仓库快照、同一任务输入、同一约束和同一评分表。若模型、日期、工具权限或外部资料不同，需要在运行记录中说明。

## 运行记录建议

每次执行可在评测外部或临时分支中保存记录，例如：

```text
benchmarks/runs/
  2026-06-14-GT-BENCH-001-baseline/
    run-notes.md
    final-response.md
    diff.patch
  2026-06-14-GT-BENCH-001-goal-teams/
    run-notes.md
    final-response.md
    diff.patch
```

本仓库当前只要求提交任务模板；运行结果是否入库由 Lead 或维护者决定。

## 评分原则

- 先看是否完成任务和遵守范围，再看协作过程是否带来额外价值。
- Goal Teams 不因“成员更多”自动得分；必须体现更清晰的 owner、验证、风险控制或产物完整度。
- 成本不是唯一目标，但 tokens、费用和耗时必须透明记录；缺失时标记为“未提供”。
- 评分需要引用证据：文件路径、diff、测试输出、最终回复或运行记录。

当前任务入口：

- [`tasks/GT-BENCH-001/task.md`](tasks/GT-BENCH-001/task.md)：benchmark 文档模板新增任务。
- [`tasks/GT-BENCH-002/task.md`](tasks/GT-BENCH-002/task.md)：生产流门禁包任务，比较 release gate、证据完整度、自动续跑和安全边界。
- [`tasks/GT-BENCH-003/task.md`](tasks/GT-BENCH-003/task.md)：界面 E2E、复刻像素级对比和证据不足打回任务。

可用 `scripts/benchmark/benchmark-runner.py --check-only` 检查 benchmark task package 结构；兼容入口 `scripts/benchmark-runner.py --check-only` 仍可用。该脚本只检查文件和关键字段，不执行真实任务。
