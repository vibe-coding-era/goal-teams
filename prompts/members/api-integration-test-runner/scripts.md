# API Integration Test Runner Scripts

- 默认运行 `python -m pytest` 执行 API 集成测试。
- 可运行项目已有启动命令，但不得触碰真实生产服务或未授权凭证。
- 使用退出码、pytest 报告、日志和响应样本作为证据。
- 先运行 `scripts/checks/validate-test-case-contract.py`；报告另需 observed output/state 与逐 assertion result，退出码/status 不能单独通过。
- 可用 `scripts/review/validate-dual-review.py` 校验双重复核记录。
