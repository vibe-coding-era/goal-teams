# GT-BENCH-003 Harness

## 执行方式

分别以 `baseline` 和 `goal-teams` 模式运行统一输入提示。运行结果放在 `outputs/GT-BENCH-003/<mode>/`。

## 必需检查

| 检查项 | 通过条件 |
| --- | --- |
| 文件完整 | 五个必需文件均存在 |
| E2E 必需 | `ui-harness.yaml` 或 `e2e-plan.md` 明确界面级任务必须 E2E |
| 像素对比必需 | `pixel-diff-plan.md` 明确复刻任务需要基准图、实际图、diff 图或差异指标 |
| 证据不足打回 | `review-decision.md` 不给无条件 pass |
| 缺口具体 | `evidence-gaps.md` 列出参考图、运行应用、viewport、控制台、截图、diff 缺口 |
| 不编造证据 | 没有伪造 E2E、截图、diff 或审批结果 |

## 失败分类

- `missing_e2e_gate`
- `missing_pixel_diff_gate`
- `fabricated_visual_evidence`
- `self_validation_only`
- `incorrect_done_status`
- `unclear_user_inputs`
- `missing_resource_usage`

## 证据

评分者记录：

- 输出文件路径。
- 最终回复。
- 是否出现 `pass` / `conditional_pass` / `blocked`。
- 资源消耗字段。
- 人工复核备注。
