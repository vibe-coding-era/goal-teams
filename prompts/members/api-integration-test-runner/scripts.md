# API Integration Test Runner Scripts

- 默认运行 `python -m pytest` 执行 API 集成测试。
- 可运行项目已有启动命令，但不得触碰真实生产服务或未授权凭证。
- 使用退出码、pytest 报告、日志和响应样本作为证据。
- 可用 `scripts/review/validate-dual-review.py` 校验双重复核记录。
