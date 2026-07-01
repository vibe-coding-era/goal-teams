# Unit Test Runner Scripts

- 按项目约定运行单元测试命令，例如 `python -m pytest tests/unit`, `npm test -- --runInBand`, `go test ./...`。
- 使用 shell 退出码和测试报告作为确定性证据；不要只写人工判断。
- 可用 `scripts/review/validate-dual-review.py` 校验双重复核记录。
- 命令不可用时记录 failure_report、环境信息和下一步。
