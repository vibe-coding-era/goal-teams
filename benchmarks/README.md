# Goal Teams Benchmarks

本目录用于沉淀可复盘的 benchmark 任务，评估 Goal Teams 相比单会话或临时协作方式是否真的带来更好的结果。V2.38 runner 既检查 task package，也可解析 `codex exec --json` 的 observer usage；真实 provider 执行仍需显式选择，默认检查不会消费模型调用。

## 目标

- 用同一份任务输入比较 `baseline`、`goal-teams` 及任务指定的版本化执行模式。
- 记录产物质量、范围遵守、独立校验、文档完整度、耗时、tokens、缓存覆盖和费用。
- 用 V2.43 的十二项工程指标记录本次、上一次和近期平均值，并生成自包含 OKF 用户报告。
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
    GT-BENCH-004/
      task.md
      harness.md
      scoring.md
      expected-artifacts.md
```

新增 benchmark 时优先复制 `GT-BENCH-001` 的结构，并保持任务编号稳定。任务编号建议使用 `GT-BENCH-NNN`。

## 执行模式

- `baseline`：单个 Codex 会话按任务提示直接完成，不显式启动 Goal Teams。
- `goal-teams`：由 Goal Lead 拆分成员，成员按 locked scope 和独立校验要求完成。
- `goal-teams-v2.02`：按 V2.02 规则执行，用于和后续 LOOP 协议做版本对照。
- `goal-teams-v2.1-loop`：按 V2.1 Lead LOOP Protocol 执行，重点观察中途缺证、自动续跑、停止边界和状态恢复。
- `review-only`：可选，只评分不执行，用于训练评分一致性。

各执行模式必须使用同一仓库快照、同一任务输入、同一约束和同一评分表。若模型、日期、工具权限或外部资料不同，需要在运行记录中说明。

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

## V2.43 工程指标记录

每个 Benchmark run 使用 `references/engineering-metrics-protocol.md` 和 `references/engineering-metrics-manifest.json` 定义的同一算法。运行目录建议包含：

```text
<run>/
  metrics/
    metric-events.jsonl
    metric-summary.json
    engineering-metrics.md
```

run record 中的 `engineering_metrics` 至少记录：

```json
{
  "schema_version": "goal-teams-engineering-metrics-v2.43",
  "current": {},
  "previous": {},
  "recent": {},
  "recent_sample_count": 0,
  "report_path": "metrics/engineering-metrics.md"
}
```

`summary.json`、Benchmark Markdown report 与 `engineering-metrics.md` 必须读取同一 calculator 输出，不能各自实现公式。可比较样本默认使用 `scenario_id + execution_mode + rubric_digest + model_and_config_identity + metric_schema_version`，近期窗口为当前 run 之前最近 20 个样本；比例使用 pooled numerator/denominator，少于 5 个样本标记 `insufficient_sample`。

blind-agent 运行通过可重复的 `--metrics-history <metric-summary.json-or-directory>` 显式装载此前 summary；calculator 再按上述 cohort key 筛选 previous/recent。没有传入真实历史时保持无历史状态，不得由当前 run 或 `quality_pass_rate` 伪造比较值。

用户报告必须是 OKF Concept Document，四列表格覆盖 FPAR、LCC、HER、SAR、CPAC、DER、RRR、CWR、SDI、RFR、ARCR、MRT，并自包含每项算法、分子/分母、排除项、上一次选择、近期聚合、状态和 Evidence refs。缺可信数据使用 `unavailable`，观察窗未结束使用 `pending`，不适用使用 `not_applicable`，均不得写成零。

十二项指标在 V2.43 第一版只作为观察维度，不自动进入 Benchmark 100 分评分，也不替代 Harness、Evidence 或 Completion Audit。最终用户回复不展开完整指标表，只提供真实生成的 OKF 报告链接并提醒打开查看。

## 评分原则

- 先看是否完成任务和遵守范围，再看协作过程是否带来额外价值。
- Goal Teams 不因“成员更多”自动得分；必须体现更清晰的 owner、验证、风险控制或产物完整度。
- 成本不是唯一目标，但 tokens、费用和耗时必须透明记录；缺失时标记为“未提供”。
- 评分需要引用证据：文件路径、diff、测试输出、最终回复或运行记录。

当前任务入口：

- [`tasks/GT-BENCH-001/task.md`](tasks/GT-BENCH-001/task.md)：benchmark 文档模板新增任务。
- [`tasks/GT-BENCH-002/task.md`](tasks/GT-BENCH-002/task.md)：生产流门禁包任务，比较 release gate、证据完整度、自动续跑和安全边界。
- [`tasks/GT-BENCH-003/task.md`](tasks/GT-BENCH-003/task.md)：界面 E2E、复刻像素级对比和证据不足打回任务。
- [`tasks/GT-BENCH-004/task.md`](tasks/GT-BENCH-004/task.md)：V2.1 Lead LOOP Protocol 任务，比较中途缺证、自动续跑、停止边界和状态恢复。

可用 `scripts/benchmark/benchmark-runner.py --check-only` 检查 task package；兼容入口仍可用。`scripts/benchmark/cache-probe.py --route benchmark` 只生成 baseline-current、dynamic-suffix-change、stable-prefix-candidate 三组“1 次 first-seen reference + 5 次 repeat”计划，不执行 provider 请求，live A/B 为 unavailable。blind-agent runner 从 staged package 绑定 route-static identity、有效配置边界和 observer telemetry；最终 prompt 不可见时 cache analytics 不得声称 runtime digest 或 request hit rate。
