# GT-BENCH-001 Expected Artifacts

本文件定义一次合格执行应产生的最小产物。评分者可以用它检查 diff 和最终回复。

## 必需文件

| 文件 | 必需内容 |
| --- | --- |
| `benchmarks/README.md` | benchmark 目的、目录结构、执行模式、运行记录建议和评分原则。 |
| `benchmarks/tasks/GT-BENCH-001/task.md` | 任务目的、统一输入提示、允许范围、禁止范围、Done Criteria。 |
| `benchmarks/tasks/GT-BENCH-001/harness.md` | 人工运行步骤、baseline 与 Goal Teams 执行差异、证据采集、停止条件。 |
| `benchmarks/tasks/GT-BENCH-001/scoring.md` | 100 分评分表、扣分规则、严重缺陷标记、模式对比方法。 |
| `benchmarks/tasks/GT-BENCH-001/expected-artifacts.md` | 必需文件、最终回复要求、Lead 整合建议和验收清单。 |

## 最终回复要求

执行者完成后应使用中文返回：

- 变更文件。
- benchmark 结构摘要。
- 需要 Lead 整合的校验脚本或 README 同步点。
- 已运行和未运行的校验。
- 阻塞或剩余风险；没有则写“无”。

若运行时没有 tokens 或费用数据，写 `未提供`，不要估算。

## Lead 整合建议

本任务的执行者不应直接修改根 README 或校验脚本，但可以建议 Lead 后续整合：

- 在 `README.md` 和 `README.en.md` 的发布内容中加入 `benchmarks/`。
- 在 `scripts/validate.py` 的必需文件列表中加入 benchmark 入口和 `GT-BENCH-001` 四个任务文件。
- 在发布说明或 CHANGELOG 中说明 V1.7 新增 benchmark 评估模板。
- 如未来要保存运行结果，明确 `benchmarks/runs/` 是否纳入版本控制。

## 验收清单

- [ ] 所有新增文件位于 `benchmarks/` 下。
- [ ] 任务可在没有额外 runner 的情况下人工执行。
- [ ] baseline 与 Goal Teams 使用相同输入和评分表。
- [ ] 评分标准能检查范围、质量、复盘性、校验和成本。
- [ ] 文档没有承诺未验证 CLI 或自动化能力。
- [ ] 最终回复包含校验情况和 Lead 同步建议。

## 可选产物

以下产物可在实际 benchmark 运行时生成，但不是模板提交的必需内容：

```text
benchmarks/runs/<date>-GT-BENCH-001-<mode>/
  run-notes.md
  final-response.md
  diff.patch
  validation-output.txt
```

运行结果是否提交入库由 Lead 或维护者决定。
