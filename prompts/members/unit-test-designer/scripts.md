# Unit Test Designer Scripts

- 优先使用项目已有测试命令，例如 `pytest`、`npm test`、`pnpm test`、`go test`、`cargo test`。
- 若测试文件是 Python，可使用 `python -m pytest <path>` 做语法和收集检查。
- 可用 `scripts/check.sh` 做 Skill 包结构校验；业务项目测试以项目自身命令为准。
- V2.35 contract 先运行 `scripts/checks/validate-test-case-contract.py <case.json>`；兼容入口为 `scripts/validate-test-case-contract.py`。
- 不为通过测试而修改生产实现代码；缺少依赖或测试环境时记录 failure_report。
