# API Integration Test Designer Scripts

- 默认生成可由 `python -m pytest <path>` 执行的 API 集成测试脚本。
- 可使用项目已有 HTTP client、test client、fixture 和 mock server。
- 不凭空要求真实外部服务或凭证；需要时写入 blocked 和 approval_gate。
- 可用 `scripts/harness/validate-harness.py` 检查 Harness 字段完整性。
- 使用 Goal Packet/Harness 指定的 V2.44 validator 检查 `integration-test-plan`、API typed fields、四段合同、input/output bindings 与非 exit/status 业务断言；不得通过调用旧入口绕过新字段。
- 用安全的仓库相对路径计算测试文件 sha256，并运行框架的 collect/list 命令证明真实 discovery；path、hash、node/case ID 一并写入交接物。
- discovery、validator 或 denominator coverage 失败时退出非零并保留机器错误码；不得降级成 prose warning。
