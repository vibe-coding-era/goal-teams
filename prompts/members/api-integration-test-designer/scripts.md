# API Integration Test Designer Scripts

- 默认生成可由 `python -m pytest <path>` 执行的 API 集成测试脚本。
- 可使用项目已有 HTTP client、test client、fixture 和 mock server。
- 不凭空要求真实外部服务或凭证；需要时写入 blocked 和 approval_gate。
- 可用 `scripts/harness/validate-harness.py` 检查 Harness 字段完整性。
