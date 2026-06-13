# GT-BENCH-002 Expected Artifacts

本文件定义 benchmark 模板本身和一次合格运行应产生的最小产物。评分者可以用它检查 diff、输出目录和最终回复。

## 模板必需文件

| 文件 | 必需内容 |
| --- | --- |
| `benchmarks/tasks/GT-BENCH-002/task.md` | 任务目的、统一输入提示、允许范围、禁止范围、Done Criteria。 |
| `benchmarks/tasks/GT-BENCH-002/harness.md` | baseline 与 Goal Teams 执行方法、证据采集、停止条件和对照表。 |
| `benchmarks/tasks/GT-BENCH-002/scoring.md` | 100 分评分表、扣分规则、严重缺陷标记和模式对比方法。 |
| `benchmarks/tasks/GT-BENCH-002/expected-artifacts.md` | 模板文件、运行输出、最终回复要求、Lead 整合建议和验收清单。 |

## 运行输出必需文件

实际 benchmark 运行应在 `outputs/GT-BENCH-002/<mode>/` 下产生：

| 文件 | 必需内容 |
| --- | --- |
| `release-gate.md` | 门禁结论、证据摘要、缺口、风险、下一步；缺证时不能无条件 `pass`。 |
| `evidence-ledger.json` | 有效 JSON；列出证据项、来源路径、owner、validator、status、gap 和 evidence_ref。 |
| `pipeline-gates.yaml` | 范围门、SPEC 门、测试证据门、生产安全门、收尾审计门，每个门包含 owner、inputs、pass_criteria、block_conditions、decision。 |
| `auto-continue-plan.md` | 可自动续跑项、必须停止项、owner、触发条件和预期证据。 |
| `safety-boundaries.md` | 禁止行为、审批边界、凭证/生产/支付/认证限制和编造证据限制。 |

## 最终回复要求

执行者完成后应使用中文返回：

- 变更文件。
- release gate 结论。
- 证据缺口摘要。
- 自动续跑项与停止条件。
- 已运行和未运行的校验。
- 阻塞或剩余风险；没有则写“无”。
- 资源消耗（用户 / tokens / 费用）；没有运行时数据写 `未提供`。

## Lead 整合建议

本任务的执行者不应直接修改根 README、Skill、runtime 或校验脚本，但可以建议 Lead 后续整合：

- 在 `benchmarks/README.md` 的任务入口中加入 `GT-BENCH-002`。
- 在 `README.md` 和 `README.en.md` 的发布说明中说明新增生产流门禁 benchmark。
- 由 Lead 决定是否把 `GT-BENCH-002` 四个模板文件加入 `scripts/validate.py` 必需文件列表。
- 若未来保存运行结果，明确 `outputs/` 或 `benchmarks/runs/` 的留存策略，避免把真实凭证或生产日志提交入库。

## 验收清单

- [ ] `GT-BENCH-002` 至少包含四个模板文件。
- [ ] 统一输入提示要求静态 Markdown/YAML/JSON，不要求真实生产接入。
- [ ] 评分标准能比较 baseline 与 goal-teams 在 release gate、证据完整度、自动续跑和安全边界上的差异。
- [ ] Done Criteria 阻止缺证时无条件放行。
- [ ] harness 能采集最终 diff、门禁结论、证据缺口、自动续跑项、停止条件和资源消耗。
- [ ] Lead 同步点明确，且模板执行者不需要越界修改 README、SKILL、runtime 或 `validate.py`。

## 可选产物

以下产物可在实际 benchmark 运行时生成，但不是模板提交的必需内容：

```text
outputs/GT-BENCH-002/<mode>/
  run-notes.md
  final-response.md
  diff.patch
  validation-output.txt
```

运行结果是否提交入库由 Lead 或维护者决定。
