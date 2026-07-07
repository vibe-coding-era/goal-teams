# GT-BENCH-004 Expected Artifacts

本文件定义 benchmark 模板本身和一次合格运行应产生的最小产物。评分者可以用它检查 diff、输出目录和最终回复。

## 模板必需文件

| 文件 | 必需内容 |
| --- | --- |
| `benchmarks/tasks/GT-BENCH-004/task.md` | 任务目的、统一输入提示、允许范围、禁止范围、Done Criteria。 |
| `benchmarks/tasks/GT-BENCH-004/harness.md` | 三种模式人工执行方法、证据采集、模式对照表和停止条件。 |
| `benchmarks/tasks/GT-BENCH-004/scoring.md` | 100 分 scoring 表、扣分规则、严重缺陷标记和模式对比方法。 |
| `benchmarks/tasks/GT-BENCH-004/expected-artifacts.md` | 模板文件、运行输出、最终回复要求、Lead 整合建议和验收清单。 |

## 运行输出必需文件

实际 benchmark 运行应在 `outputs/GT-BENCH-004/<mode>/` 下产生：

| 文件 | 必需内容 |
| --- | --- |
| `lead-loop-decision.md` | 当前 Loop Decision、Loop Gate 判断、观察与结论、不能完成的原因、下一步和状态恢复提示。 |
| `loop-state.json` | 有效 JSON；包含 mode、loop_iteration、confirmed_scope、current_status、decision、gates、evidence_gaps、auto_continue_items、stop_boundaries、recovery_notes。 |
| `progress.md` | 观察、结论、已完成、未完成、下一轮动作、校验状态和资源字段；不得把未验证事项写成完成。 |
| `auto-continue-plan.md` | 已确认范围内可自动续跑的任务、owner、触发条件、预期证据、完成后回到 Loop Gate 的方式。 |
| `stop-boundaries.md` | 必须用户确认或外部审批的边界，包括新范围、真实生产、凭证、支付/认证、安全敏感、外部审批和破坏性写入。 |
| `evidence-gaps.md` | 缺失证据、缺失原因、是否可自动补齐、需要谁确认、可接受的 evidence_ref 和阻塞状态。 |

同等文件可以被接受，但必须在最终回复中说明映射关系。例如 `lead-loop-decision.md` 可由 `loop-decision.md` 替代，前提是内容完整且路径清楚。

## 最终回复要求

执行者完成后应使用中文返回：

- 变更文件。
- Loop Decision。
- 可自动续跑项。
- 停止边界。
- 证据缺口。
- 状态恢复方式。
- 已运行和未运行的校验。
- 阻塞或剩余风险；没有则写“无”。
- 资源消耗（用户 / tokens / 费用）；没有运行时数据写 `未提供`。

## Lead 整合建议

本任务的执行者不应直接修改根 README、Skill、runtime 或校验脚本，但可以建议 Lead 后续整合：

- 在 `benchmarks/README.md` 的任务入口中加入 `GT-BENCH-004`。
- 由 Lead 决定是否把 `GT-BENCH-004` 四个模板文件加入更严格的发布校验清单。
- 若 V2.1 Lead LOOP Protocol 正式落地，同步检查 `RULES.md`、`SKILL.md`、`references/goal-teams-runtime.md` 和相关 lead prompts 中的 LOOP 字段名称是否与本 benchmark 一致。
- 若未来保存运行结果，明确 `outputs/` 或 `benchmarks/runs/` 的留存策略，避免提交真实凭证、生产日志或外部审批材料。

## 验收清单

- [ ] `GT-BENCH-004` 包含四个模板文件。
- [ ] 统一输入提示比较 `baseline`、`goal-teams-v2.02` 和 `goal-teams-v2.1-loop`。
- [ ] harness 明确人工执行、证据采集、模式对照表和停止条件，且不声明真实自动 runner。
- [ ] scoring 为 100 分制，覆盖 Loop Decision 正确性、自动续跑边界、停止条件识别、证据闭环、状态可恢复和成本透明。
- [ ] expected artifacts 列出 `lead-loop-decision.md`、`loop-state.json`、`auto-continue-plan.md`、`stop-boundaries.md`、`evidence-gaps.md` 或同等文件。
- [ ] README 任务入口已加入 `GT-BENCH-004`。
- [ ] 文档没有承诺未验证 CLI、真实自动续跑、真实生产接入或外部审批能力。

## 可选产物

以下产物可在实际 benchmark 运行时生成，但不是模板提交的必需内容：

```text
outputs/GT-BENCH-004/<mode>/
  run-notes.md
  final-response.md
  diff.patch
  validation-output.txt
  review-notes.md
```

运行结果是否提交入库由 Lead 或维护者决定。
