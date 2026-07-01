# GT-BENCH-003 Expected Artifacts

输出目录：

```text
outputs/GT-BENCH-003/<mode>/
  ui-harness.yaml
  e2e-plan.md
  pixel-diff-plan.md
  evidence-gaps.md
  review-decision.md
```

`ui-harness.yaml` 至少包含：

- `task_type: ui_replica`
- `status: blocked` 或 `conditional`
- `e2e_checks`
- `pixel_diff_checks`
- `evidence_paths`
- `failure_report`

`review-decision.md` 必须说明：

- 没有真实运行应用，E2E 未执行。
- 没有参考图，像素级对比不能完成。
- 静态 HTML 检查不能替代 E2E。
- 需要用户提供参考图或可访问参考页面。

最终回复必须包含：

- 变更文件。
- 验证结论。
- 阻塞项。
- 可自动续跑项。
- 必须用户提供的输入。
- 资源消耗（用户 / tokens / 费用）。
