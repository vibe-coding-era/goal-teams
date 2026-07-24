# API Integration Test Runner Scripts

- 默认运行 `python -m pytest` 执行 API 集成测试。
- 可运行项目已有启动命令，但不得触碰真实生产服务或未授权凭证。
- 使用退出码、pytest 报告、日志、响应样本、post-state 与 side-effect observations 作为联合证据。
- 先运行 Goal Packet/Harness 指定的 plan/case validator、sha256 复核和 discovery；执行后运行指定 `test-run-result` validator。
- 报告必须含 observed output/state、逐 assertion result、首次 attempt、所有 retry、cleanup 和 artifact hashes；退出码/status 不能单独通过。
- 不使用 `--last-failed`、自动 rerun 或隐藏重试作为最终 green；诊断 retry 必须显式记录并把 fail→pass 判为 flaky。
- 可用 `scripts/review/validate-dual-review.py` 校验双重复核记录。
