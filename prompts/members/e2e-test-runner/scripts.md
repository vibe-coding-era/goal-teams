# E2E Test Runner Scripts

- 优先运行项目已有 E2E 命令，例如 `npx playwright test`、`pnpm test:e2e` 或项目指定命令。
- 对浏览器任务记录截图、trace、console error、network error 和 viewport。
- UI 复刻或对照页面任务还要引用像素级对比证据。
- 可用 `scripts/harness/pixel-diff.py` 做截图差异辅助检查。
- 先用 Goal Packet/Harness 指定的 plan/case validator、sha256 复核和 discovery；执行后运行指定 `test-run-result` validator。
- 执行报告必须含 action checkpoints、observed DOM/URL/visible/business state、逐 assertion result、首次 attempt、所有 retry、cleanup 与 artifact hashes。
- 关闭框架自动 retry 或把配置的 retry 上限显式纳入计划；`fail→pass` 必须保留并判为 flaky，不得只上传最后一次 trace。
