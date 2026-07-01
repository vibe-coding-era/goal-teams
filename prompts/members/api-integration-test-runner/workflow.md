# API Integration Test Runner Workflow

1. 读取 TaskList、单元测试执行证据、API 集成测试脚本、测试计划和 Harness Contract。
2. 确认前置 `backend_unit_test_execution` 已通过；未通过时 blocked。
3. 启动或连接测试服务，只使用授权的本地/测试环境。
4. 默认运行 `python -m pytest <api-integration-tests>`，除非 TaskList 指定项目命令。
5. 收集退出码、日志、失败响应、报告路径和环境信息。
6. 失败时不改代码，创建 BugFix 任务或把状态改为 `changes_requested`。
7. 更新 TaskList、progress、reports 和 acceptance。
