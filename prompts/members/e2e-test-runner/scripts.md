# E2E Test Runner Scripts

- 优先运行项目已有 E2E 命令，例如 `npx playwright test`、`pnpm test:e2e` 或项目指定命令。
- 对浏览器任务记录截图、trace、console error、network error 和 viewport。
- UI 复刻或对照页面任务还要引用像素级对比证据。
- 可用 `scripts/harness/pixel-diff.py` 做截图差异辅助检查。
- 先用 `scripts/checks/validate-test-case-contract.py` 验证 contract；执行报告必须另含 observed DOM/URL/state 与逐 assertion result。
