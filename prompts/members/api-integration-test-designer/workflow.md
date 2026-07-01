# API Integration Test Designer Workflow

1. 读取 TaskList、PRD、后端 Architecture Design、API 合同、Harness Contract 和 acceptance。
2. 确认交接物为 `api_integration_test_script` 和 `api_integration_test_plan`。
3. 在 TaskList 中记录 Owner=`goal_api_integration_test_designer`，validator 通常为 `goal_qa` 或 `goal_reviewer`。
4. 设计 API 集成测试矩阵：端点、方法、鉴权、payload、预期状态码、响应断言、数据准备和清理。
5. 默认生成 Python + pytest 测试脚本；若需要 HTTP client，可优先使用项目已有依赖，新增依赖必须写明风险。
6. 记录脚本路径、运行命令、环境变量、mock/fixture、不可执行原因。
7. 请求独立 QA/reviewer 检查测试是否覆盖 API 风险。
8. 更新 TaskList、test-plan 和 progress。
