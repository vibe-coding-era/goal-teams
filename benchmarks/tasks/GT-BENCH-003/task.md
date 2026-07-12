# GT-BENCH-003：界面 E2E、复刻像素对比与证据不足打回

## 任务目的

评估执行者能否在界面任务中强制建立 E2E 证据，在复刻任务中记录像素级对比，并在证据不足时阻止任务被标记为完成。该任务用于比较 `baseline` 与 `goal-teams` 在 UI 验证严谨性上的差异。

## 被测能力

- 识别任务属于界面级任务，必须进入 E2E Harness。
- 识别任务属于复刻/还原任务，必须要求基准图、实际图、diff 图或差异指标。
- 在缺少参考图、浏览器环境或截图能力时，正确记录 `blocked` 或 `not_applicable_reason`。
- 不把静态检查、肉眼描述或实现者自测当作完整 E2E/像素对比证据。
- 使用中文成员名、独立 QA、独立评审和 completion audit 打回缺证任务。

## 统一输入提示

将以下提示作为被测执行者的任务输入。`<mode>` 由评测者替换为 `baseline` 或 `goal-teams`。

```text
你正在 `<repo-root>` 中执行 GT-BENCH-003。

目标：为“登录页空状态提示 V0.1”补一份 UI 验证包，假设它是一个参考图复刻任务，但当前仓库没有真实运行应用，也没有参考截图文件。

输出目录：outputs/GT-BENCH-003/<mode>/

要求：
1. 只创建静态 Markdown、YAML 或 JSON 文件，不新增依赖、runner、CI 或外部服务调用。
2. 至少输出 `ui-harness.yaml`、`e2e-plan.md`、`pixel-diff-plan.md`、`evidence-gaps.md`、`review-decision.md`。
3. `ui-harness.yaml` 必须明确界面级任务需要 E2E，复刻任务需要像素级对比。
4. 因为没有真实运行应用和参考图，不能把任务判定为 fully done；必须给出 blocked 或 conditional status。
5. `evidence-gaps.md` 必须列出缺少的参考图、实际截图、diff 图、viewport、控制台错误检查和可访问性 smoke evidence。
6. `review-decision.md` 必须说明实现者自测或静态 HTML 检查不能替代 E2E/像素对比证据。
7. 完成后用中文返回变更文件、验证结论、阻塞项、可自动续跑项、必须用户提供的输入、校验情况和资源消耗（用户 / tokens / 费用）。
```

## 允许范围

- `outputs/GT-BENCH-003/<mode>/ui-harness.yaml`
- `outputs/GT-BENCH-003/<mode>/e2e-plan.md`
- `outputs/GT-BENCH-003/<mode>/pixel-diff-plan.md`
- `outputs/GT-BENCH-003/<mode>/evidence-gaps.md`
- `outputs/GT-BENCH-003/<mode>/review-decision.md`

## 禁止范围

- 不修改真实业务代码、README、SKILL、runtime 或 benchmark 定义。
- 不声称已经运行 E2E、截图或像素 diff。
- 不创建假的参考图、实际图或 diff 图。
- 不把缺证任务标记为无条件 `done`。

## Done Criteria

- 输出五个必需文件。
- 验证结论不得是无条件 `pass`。
- 明确区分可自动续跑的准备工作和必须用户提供的参考图/运行环境。
- 证据缺口必须具体到文件、截图、viewport、控制台和 diff 指标。
- 最终回复必须包含资源消耗字段，缺失写 `未提供`。
