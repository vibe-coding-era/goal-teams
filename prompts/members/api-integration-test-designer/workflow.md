# API Integration Test Designer Workflow

1. 读取 TaskList、PRD、后端 Architecture Design、API 合同、Harness Contract 和 acceptance。
2. 确认交接物为 `api_integration_test_script` 和 `api_integration_test_plan`。
3. 提交 revision-bound ledger event/patch，Owner=`goal_api_integration_test_designer`，validator 通常为 `goal_qa` 或 `goal_reviewer`；不得直接编辑 TaskList。
4. 设计 API 集成测试矩阵：端点、方法、鉴权、payload、预期状态码、响应断言、数据准备和清理。
5. 按 `references/test-case-assertion-protocol.md` 把输入、处理、输出和业务断言写成 contract；状态码必须配合业务 observable。
6. 默认生成 Python + pytest 测试脚本；若需要 HTTP client，可优先使用项目已有依赖，新增依赖必须写明风险。
7. 运行 `scripts/checks/validate-test-case-contract.py`，记录脚本/contract 路径、运行命令、环境变量、mock/fixture、不可执行原因。
8. 请求独立 QA/reviewer 检查测试是否覆盖 API 风险。
9. 更新被分配的 test-plan 和 progress，并提交带 revision 的 ledger event/patch；不得直接编辑 TaskList。
